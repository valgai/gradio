"""
This file defines a useful high-level abstraction to build Gradio chatbots: ChatInterface.
"""

from __future__ import annotations

import functools
import inspect
import warnings
from typing import AsyncGenerator, Callable, Literal, Union, cast

import anyio
from gradio_client.documentation import document

from gradio.blocks import Blocks
from gradio.components import (
    Button,
    Chatbot,
    Component,
    Markdown,
    MultimodalTextbox,
    State,
    Textbox,
    get_component_instance,
)
from gradio.components.chatbot import FileDataDict, Message, MessageDict, TupleFormat
from gradio.components.multimodal_textbox import MultimodalData
from gradio.events import Dependency, on
from gradio.helpers import create_examples as Examples  # noqa: N812
from gradio.helpers import special_args
from gradio.layouts import Accordion, Group, Row
from gradio.routes import Request
from gradio.themes import ThemeClass as Theme
from gradio.utils import SyncToAsyncIterator, async_iteration, async_lambda


@document()
class ChatInterface(Blocks):
    """
    ChatInterface is Gradio's high-level abstraction for creating chatbot UIs, and allows you to create
    a web-based demo around a chatbot model in a few lines of code. Only one parameter is required: fn, which
    takes a function that governs the response of the chatbot based on the user input and chat history. Additional
    parameters can be used to control the appearance and behavior of the demo.

    Example:
        import gradio as gr

        def echo(message, history):
            return message

        demo = gr.ChatInterface(fn=echo, examples=["hello", "hola", "merhaba"], title="Echo Bot")
        demo.launch()
    Demos: chatinterface_multimodal, chatinterface_random_response, chatinterface_streaming_echo
    Guides: creating-a-chatbot-fast, sharing-your-app
    """

    def __init__(
        self,
        fn: Callable,
        *,
        multimodal: bool = False,
        msg_format: Literal["messages", "tuples"] = "tuples",
        chatbot: Chatbot | None = None,
        textbox: Textbox | MultimodalTextbox | None = None,
        additional_inputs: str | Component | list[str | Component] | None = None,
        additional_inputs_accordion_name: str | None = None,
        additional_inputs_accordion: str | Accordion | None = None,
        examples: list[str] | list[dict[str, str | list]] | list[list] | None = None,
        cache_examples: bool | Literal["lazy"] | None = None,
        examples_per_page: int = 10,
        title: str | None = None,
        description: str | None = None,
        theme: Theme | str | None = None,
        css: str | None = None,
        js: str | None = None,
        head: str | None = None,
        analytics_enabled: bool | None = None,
        submit_btn: str | None | Button = "Submit",
        stop_btn: str | None | Button = "Stop",
        retry_btn: str | None | Button = "🔄  Retry",
        undo_btn: str | None | Button = "↩️ Undo",
        clear_btn: str | None | Button = "🗑️  Clear",
        autofocus: bool = True,
        concurrency_limit: int | None | Literal["default"] = "default",
        fill_height: bool = True,
        delete_cache: tuple[int, int] | None = None,
        show_progress: Literal["full", "minimal", "hidden"] = "minimal",
    ):
        """
        Parameters:
            fn: The function to wrap the chat interface around. Should accept two parameters: a string input message and list of two-element lists of the form [[user_message, bot_message], ...] representing the chat history, and return a string response. See the Chatbot documentation for more information on the chat history format.
            multimodal: If True, the chat interface will use a gr.MultimodalTextbox component for the input, which allows for the uploading of multimedia files. If False, the chat interface will use a gr.Textbox component for the input.
            chatbot: An instance of the gr.Chatbot component to use for the chat interface, if you would like to customize the chatbot properties. If not provided, a default gr.Chatbot component will be created.
            textbox: An instance of the gr.Textbox or gr.MultimodalTextbox component to use for the chat interface, if you would like to customize the textbox properties. If not provided, a default gr.Textbox or gr.MultimodalTextbox component will be created.
            additional_inputs: An instance or list of instances of gradio components (or their string shortcuts) to use as additional inputs to the chatbot. If components are not already rendered in a surrounding Blocks, then the components will be displayed under the chatbot, in an accordion.
            additional_inputs_accordion_name: Deprecated. Will be removed in a future version of Gradio. Use the `additional_inputs_accordion` parameter instead.
            additional_inputs_accordion: If a string is provided, this is the label of the `gr.Accordion` to use to contain additional inputs. A `gr.Accordion` object can be provided as well to configure other properties of the container holding the additional inputs. Defaults to a `gr.Accordion(label="Additional Inputs", open=False)`. This parameter is only used if `additional_inputs` is provided.
            examples: Sample inputs for the function; if provided, appear below the chatbot and can be clicked to populate the chatbot input. Should be a list of strings if `multimodal` is False, and a list of dictionaries (with keys `text` and `files`) if `multimodal` is True.
            cache_examples: If True, caches examples in the server for fast runtime in examples. The default option in HuggingFace Spaces is True. The default option elsewhere is False.
            examples_per_page: If examples are provided, how many to display per page.
            title: a title for the interface; if provided, appears above chatbot in large font. Also used as the tab title when opened in a browser window.
            description: a description for the interface; if provided, appears above the chatbot and beneath the title in regular font. Accepts Markdown and HTML content.
            theme: Theme to use, loaded from gradio.themes.
            css: Custom css as a string or path to a css file. This css will be included in the demo webpage.
            js: Custom js as a string or path to a js file. The custom js should be in the form of a single js function. This function will automatically be executed when the page loads. For more flexibility, use the head parameter to insert js inside <script> tags.
            head: Custom html to insert into the head of the demo webpage. This can be used to add custom meta tags, multiple scripts, stylesheets, etc. to the page.
            analytics_enabled: Whether to allow basic telemetry. If None, will use GRADIO_ANALYTICS_ENABLED environment variable if defined, or default to True.
            submit_btn: Text to display on the submit button. If None, no button will be displayed. If a Button object, that button will be used.
            stop_btn: Text to display on the stop button, which replaces the submit_btn when the submit_btn or retry_btn is clicked and response is streaming. Clicking on the stop_btn will halt the chatbot response. If set to None, stop button functionality does not appear in the chatbot. If a Button object, that button will be used as the stop button.
            retry_btn: Text to display on the retry button. If None, no button will be displayed. If a Button object, that button will be used.
            undo_btn: Text to display on the delete last button. If None, no button will be displayed. If a Button object, that button will be used.
            clear_btn: Text to display on the clear button. If None, no button will be displayed. If a Button object, that button will be used.
            autofocus: If True, autofocuses to the textbox when the page loads.
            concurrency_limit: If set, this is the maximum number of chatbot submissions that can be running simultaneously. Can be set to None to mean no limit (any number of chatbot submissions can be running simultaneously). Set to "default" to use the default concurrency limit (defined by the `default_concurrency_limit` parameter in `.queue()`, which is 1 by default).
            fill_height: If True, the chat interface will expand to the height of window.
            delete_cache: A tuple corresponding [frequency, age] both expressed in number of seconds. Every `frequency` seconds, the temporary files created by this Blocks instance will be deleted if more than `age` seconds have passed since the file was created. For example, setting this to (86400, 86400) will delete temporary files every day. The cache will be deleted entirely when the server restarts. If None, no cache deletion will occur.
            show_progress: whether to show progress animation while running.
        """
        super().__init__(
            analytics_enabled=analytics_enabled,
            mode="chat_interface",
            css=css,
            title=title or "Gradio",
            theme=theme,
            js=js,
            head=head,
            fill_height=fill_height,
            delete_cache=delete_cache,
        )
        self.msg_format: Literal["messages", "tuples"] = msg_format
        self.multimodal = multimodal
        self.concurrency_limit = concurrency_limit
        self.fn = fn
        self.is_async = inspect.iscoroutinefunction(
            self.fn
        ) or inspect.isasyncgenfunction(self.fn)
        self.is_generator = inspect.isgeneratorfunction(
            self.fn
        ) or inspect.isasyncgenfunction(self.fn)
        self.buttons: list[Button | None] = []

        self.examples = examples
        self.cache_examples = cache_examples

        if additional_inputs:
            if not isinstance(additional_inputs, list):
                additional_inputs = [additional_inputs]
            self.additional_inputs = [
                get_component_instance(i)
                for i in additional_inputs  # type: ignore
            ]
        else:
            self.additional_inputs = []
        if additional_inputs_accordion_name is not None:
            print(
                "The `additional_inputs_accordion_name` parameter is deprecated and will be removed in a future version of Gradio. Use the `additional_inputs_accordion` parameter instead."
            )
            self.additional_inputs_accordion_params = {
                "label": additional_inputs_accordion_name
            }
        if additional_inputs_accordion is None:
            self.additional_inputs_accordion_params = {
                "label": "Additional Inputs",
                "open": False,
            }
        elif isinstance(additional_inputs_accordion, str):
            self.additional_inputs_accordion_params = {
                "label": additional_inputs_accordion
            }
        elif isinstance(additional_inputs_accordion, Accordion):
            self.additional_inputs_accordion_params = (
                additional_inputs_accordion.recover_kwargs(
                    additional_inputs_accordion.get_config()
                )
            )
        else:
            raise ValueError(
                f"The `additional_inputs_accordion` parameter must be a string or gr.Accordion, not {type(additional_inputs_accordion)}"
            )

        with self:
            if title:
                Markdown(
                    f"<h1 style='text-align: center; margin-bottom: 1rem'>{self.title}</h1>"
                )
            if description:
                Markdown(description)

            if chatbot:
                if self.msg_format != chatbot.msg_format:
                    warnings.warn(
                        "The msg_format of the chatbot does not match the msg_format of the chat interface. The msg_format of the chat interface will be used."
                        "Recieved msg_format of chatbot: {chatbot.msg_format}, msg_format of chat interface: {self.msg_format}"
                    )
                    chatbot.msg_format = self.msg_format
                self.chatbot = get_component_instance(chatbot, render=True)
            else:
                self.chatbot = Chatbot(
                    label="Chatbot",
                    scale=1,
                    height=200 if fill_height else None,
                    msg_format=self.msg_format,
                )

            with Row():
                for btn in [retry_btn, undo_btn, clear_btn]:
                    if btn is not None:
                        if isinstance(btn, Button):
                            btn.render()
                        elif isinstance(btn, str):
                            btn = Button(
                                btn, variant="secondary", size="sm", min_width=60
                            )
                        else:
                            raise ValueError(
                                f"All the _btn parameters must be a gr.Button, string, or None, not {type(btn)}"
                            )
                    self.buttons.append(btn)  # type: ignore

            with Group():
                with Row():
                    if textbox:
                        if self.multimodal:
                            submit_btn = None
                        else:
                            textbox.container = False
                        textbox.show_label = False
                        textbox_ = get_component_instance(textbox, render=True)
                        if not isinstance(textbox_, (Textbox, MultimodalTextbox)):
                            raise TypeError(
                                f"Expected a gr.Textbox or gr.MultimodalTextbox component, but got {type(textbox_)}"
                            )
                        self.textbox = textbox_
                    elif self.multimodal:
                        submit_btn = None
                        self.textbox = MultimodalTextbox(
                            show_label=False,
                            label="Message",
                            placeholder="Type a message...",
                            scale=7,
                            autofocus=autofocus,
                        )
                    else:
                        self.textbox = Textbox(
                            container=False,
                            show_label=False,
                            label="Message",
                            placeholder="Type a message...",
                            scale=7,
                            autofocus=autofocus,
                        )
                    if submit_btn is not None and not multimodal:
                        if isinstance(submit_btn, Button):
                            submit_btn.render()
                        elif isinstance(submit_btn, str):
                            submit_btn = Button(
                                submit_btn,
                                variant="primary",
                                scale=1,
                                min_width=150,
                            )
                        else:
                            raise ValueError(
                                f"The submit_btn parameter must be a gr.Button, string, or None, not {type(submit_btn)}"
                            )
                    if stop_btn is not None:
                        if isinstance(stop_btn, Button):
                            stop_btn.visible = False
                            stop_btn.render()
                        elif isinstance(stop_btn, str):
                            stop_btn = Button(
                                stop_btn,
                                variant="stop",
                                visible=False,
                                scale=1,
                                min_width=150,
                            )
                        else:
                            raise ValueError(
                                f"The stop_btn parameter must be a gr.Button, string, or None, not {type(stop_btn)}"
                            )
                    self.buttons.extend([submit_btn, stop_btn])  # type: ignore

                self.fake_api_btn = Button("Fake API", visible=False)
                self.fake_response_textbox = Textbox(label="Response", visible=False)
                (
                    self.retry_btn,
                    self.undo_btn,
                    self.clear_btn,
                    self.submit_btn,
                    self.stop_btn,
                ) = self.buttons

            if examples:
                if self.is_generator:
                    examples_fn = self._examples_stream_fn
                else:
                    examples_fn = self._examples_fn

                self.examples_handler = Examples(
                    examples=examples,
                    inputs=[self.textbox] + self.additional_inputs,
                    outputs=self.chatbot,
                    fn=examples_fn,
                    cache_examples=self.cache_examples,
                    _defer_caching=True,
                    examples_per_page=examples_per_page,
                )

            any_unrendered_inputs = any(
                not inp.is_rendered for inp in self.additional_inputs
            )
            if self.additional_inputs and any_unrendered_inputs:
                with Accordion(**self.additional_inputs_accordion_params):  # type: ignore
                    for input_component in self.additional_inputs:
                        if not input_component.is_rendered:
                            input_component.render()

            # The example caching must happen after the input components have rendered
            if examples:
                self.examples_handler._start_caching()

            self.saved_input = State()
            self.chatbot_state = (
                State(self.chatbot.value) if self.chatbot.value else State([])
            )
            self.show_progress = show_progress
            self._setup_events()
            self._setup_api()

    def _setup_events(self) -> None:
        submit_fn = self._stream_fn if self.is_generator else self._submit_fn
        submit_triggers = (
            [self.textbox.submit, self.submit_btn.click]
            if self.submit_btn
            else [self.textbox.submit]
        )
        submit_event = (
            on(
                submit_triggers,
                self._clear_and_save_textbox,
                [self.textbox],
                [self.textbox, self.saved_input],
                show_api=False,
                queue=False,
                preprocess=False,
            )
            .then(
                self._display_input,
                [self.saved_input, self.chatbot_state],
                [self.chatbot, self.chatbot_state],
                show_api=False,
                queue=False,
            )
            .then(
                submit_fn,
                [self.saved_input, self.chatbot_state] + self.additional_inputs,
                [self.chatbot, self.chatbot_state],
                show_api=False,
                concurrency_limit=cast(
                    Union[int, Literal["default"], None], self.concurrency_limit
                ),
                show_progress=cast(
                    Literal["full", "minimal", "hidden"], self.show_progress
                ),
            )
        )
        self._setup_stop_events(submit_triggers, submit_event)

        if self.retry_btn:
            retry_event = (
                self.retry_btn.click(
                    self._delete_prev_fn,
                    [self.saved_input, self.chatbot_state],
                    [self.chatbot, self.saved_input, self.chatbot_state],
                    show_api=False,
                    queue=False,
                )
                .then(
                    self._display_input,
                    [self.saved_input, self.chatbot_state],
                    [self.chatbot, self.chatbot_state],
                    show_api=False,
                    queue=False,
                )
                .then(
                    submit_fn,
                    [self.saved_input, self.chatbot_state] + self.additional_inputs,
                    [self.chatbot, self.chatbot_state],
                    show_api=False,
                    concurrency_limit=cast(
                        Union[int, Literal["default"], None], self.concurrency_limit
                    ),
                    show_progress=cast(
                        Literal["full", "minimal", "hidden"], self.show_progress
                    ),
                )
            )
            self._setup_stop_events([self.retry_btn.click], retry_event)

        async def format_textbox(data: str | MultimodalData) -> str | dict:
            if isinstance(data, MultimodalData):
                return {"text": data.text, "files": [x.path for x in data.files]}
            else:
                return data

        if self.undo_btn:
            self.undo_btn.click(
                self._delete_prev_fn,
                [self.saved_input, self.chatbot_state],
                [self.chatbot, self.saved_input, self.chatbot_state],
                show_api=False,
                queue=False,
            ).then(
                format_textbox,
                [self.saved_input],
                [self.textbox],
                show_api=False,
                queue=False,
            )

        if self.clear_btn:
            self.clear_btn.click(
                async_lambda(lambda: ([], [], None)),
                None,
                [self.chatbot, self.chatbot_state, self.saved_input],
                queue=False,
                show_api=False,
            )

    def _setup_stop_events(
        self, event_triggers: list[Callable], event_to_cancel: Dependency
    ) -> None:
        if self.stop_btn and self.is_generator:
            if self.submit_btn:
                for event_trigger in event_triggers:
                    event_trigger(
                        async_lambda(
                            lambda: (
                                Button(visible=False),
                                Button(visible=True),
                            )
                        ),
                        None,
                        [self.submit_btn, self.stop_btn],
                        show_api=False,
                        queue=False,
                    )
                event_to_cancel.then(
                    async_lambda(lambda: (Button(visible=True), Button(visible=False))),
                    None,
                    [self.submit_btn, self.stop_btn],
                    show_api=False,
                    queue=False,
                )
            else:
                for event_trigger in event_triggers:
                    event_trigger(
                        async_lambda(lambda: Button(visible=True)),
                        None,
                        [self.stop_btn],
                        show_api=False,
                        queue=False,
                    )
                event_to_cancel.then(
                    async_lambda(lambda: Button(visible=False)),
                    None,
                    [self.stop_btn],
                    show_api=False,
                    queue=False,
                )
            self.stop_btn.click(
                None,
                None,
                None,
                cancels=event_to_cancel,
                show_api=False,
            )

    def _setup_api(self) -> None:
        if self.is_generator:

            @functools.wraps(self.fn)
            async def api_fn(message, history, *args, **kwargs):  # type: ignore
                if self.is_async:
                    generator = self.fn(message, history, *args, **kwargs)
                else:
                    generator = await anyio.to_thread.run_sync(
                        self.fn, message, history, *args, **kwargs, limiter=self.limiter
                    )
                    generator = SyncToAsyncIterator(generator, self.limiter)
                try:
                    first_response = await async_iteration(generator)
                    yield first_response, history + [[message, first_response]]
                except StopIteration:
                    yield None, history + [[message, None]]
                async for response in generator:
                    yield response, history + [[message, response]]
        else:

            @functools.wraps(self.fn)
            async def api_fn(message, history, *args, **kwargs):
                if self.is_async:
                    response = await self.fn(message, history, *args, **kwargs)
                else:
                    response = await anyio.to_thread.run_sync(
                        self.fn, message, history, *args, **kwargs, limiter=self.limiter
                    )
                history.append([message, response])
                return response, history

        self.fake_api_btn.click(
            api_fn,
            [self.textbox, self.chatbot_state] + self.additional_inputs,
            [self.textbox, self.chatbot_state],
            api_name="chat",
            concurrency_limit=cast(
                Union[int, Literal["default"], None], self.concurrency_limit
            ),
        )

    def _clear_and_save_textbox(
        self, message: str | dict
    ) -> tuple[str | dict, str | MultimodalData]:
        if self.multimodal:
            return {"text": "", "files": []}, MultimodalData(**cast(dict, message))
        else:
            return "", cast(str, message)

    def _append_multimodal_history(
        self,
        message: MultimodalData,
        response: MessageDict | str | None,
        history: list[MessageDict] | TupleFormat,
    ):
        if self.msg_format == "tuples":
            for x in message.files:
                history.append([(x.path,), None])  # type: ignore
            if message.text is None or not isinstance(message.text, str):
                return
            elif message.text == "" and message.files != []:
                history.append([None, response])  # type: ignore
            else:
                history.append([message.text, cast(str, response)])  # type: ignore
        else:
            for x in message.files:
                history.append(
                    {"role": "user", "content": cast(FileDataDict, x.model_dump())}  # type: ignore
                )
            if message.text is None or not isinstance(message.text, str):
                return
            else:
                history.append({"role": "user", "content": message.text})  # type: ignore
            if response:
                history.append(cast(MessageDict, response))  # type: ignore

    async def _display_input(
        self, message: str | MultimodalData, history: TupleFormat | list[MessageDict]
    ) -> tuple[TupleFormat, TupleFormat] | tuple[list[MessageDict], list[MessageDict]]:
        if self.multimodal and isinstance(message, MultimodalData):
            self._append_multimodal_history(message, None, history)
        elif isinstance(message, str) and self.msg_format == "tuples":
            history.append([message, None])  # type: ignore
        elif isinstance(message, str) and self.msg_format == "messages":
            history.append({"role": "user", "content": message})  # type: ignore
        return history, history  # type: ignore

    def response_as_dict(self, response: MessageDict | Message | str) -> MessageDict:
        if isinstance(response, Message):
            new_response = response.model_dump()
        elif isinstance(response, str):
            return {"role": "assistant", "content": response}
        else:
            new_response = response
        return cast(MessageDict, new_response)

    async def _submit_fn(
        self,
        message: str | MultimodalData,
        history_with_input: TupleFormat | list[MessageDict],
        request: Request,
        *args,
    ) -> tuple[TupleFormat, TupleFormat] | tuple[list[MessageDict], list[MessageDict]]:
        if self.multimodal and isinstance(message, MultimodalData):
            remove_input = (
                len(message.files) + 1
                if message.text is not None
                else len(message.files)
            )
            history = history_with_input[:-remove_input]
            message_serialized = message.model_dump()
        else:
            history = history_with_input[:-1]
            message_serialized = message

        inputs, _, _ = special_args(
            self.fn, inputs=[message_serialized, history, *args], request=request
        )

        if self.is_async:
            response = await self.fn(*inputs)
        else:
            response = await anyio.to_thread.run_sync(
                self.fn, *inputs, limiter=self.limiter
            )

        if self.msg_format == "messages":
            new_response = self.response_as_dict(response)
        else:
            new_response = response

        if self.multimodal and isinstance(message, MultimodalData):
            self._append_multimodal_history(message, new_response, history)  # type: ignore
        elif isinstance(message, str) and self.msg_format == "tuples":
            history.append([message, new_response])  # type: ignore
        elif isinstance(message, str) and self.msg_format == "messages":
            history.extend([{"role": "user", "content": message}, new_response])  # type: ignore
        return history, history  # type: ignore

    async def _stream_fn(
        self,
        message: str | MultimodalData,
        history_with_input: TupleFormat | list[MessageDict],
        request: Request,
        *args,
    ) -> AsyncGenerator:
        if self.multimodal and isinstance(message, MultimodalData):
            remove_input = (
                len(message.files) + 1
                if message.text is not None
                else len(message.files)
            )
            history = history_with_input[:-remove_input]
        else:
            history = history_with_input[:-1]
        inputs, _, _ = special_args(
            self.fn, inputs=[message, history, *args], request=request
        )

        if self.is_async:
            generator = self.fn(*inputs)
        else:
            generator = await anyio.to_thread.run_sync(
                self.fn, *inputs, limiter=self.limiter
            )
            generator = SyncToAsyncIterator(generator, self.limiter)
        try:
            first_response = await async_iteration(generator)
            if self.msg_format == "messages":
                first_response = self.response_as_dict(first_response)
            if (
                self.multimodal
                and isinstance(message, MultimodalData)
                and self.msg_format == "tuples"
            ):
                for x in message.files:
                    history.append([(x,), None])  # type: ignore
                update = history + [[message.text, first_response]]
                yield update, update
            elif (
                self.multimodal
                and isinstance(message, MultimodalData)
                and self.msg_format == "messages"
            ):
                for x in message.files:
                    history.append(
                        {"role": "user", "content": cast(FileDataDict, x.model_dump())}  # type: ignore
                    )
                update = history + [
                    {"role": "user", "content": message.text},
                    first_response,
                ]
                yield update, update
            elif self.msg_format == "tuples":
                update = history + [[message, first_response]]
                yield update, update
            else:
                update = history + [
                    {"role": "user", "content": message},
                    first_response,
                ]
                yield update, update
        except StopIteration:
            if self.multimodal and isinstance(message, MultimodalData):
                self._append_multimodal_history(message, None, history)
                yield history, history
            else:
                update = history + [[message, None]]
                yield update, update
        async for response in generator:
            if self.msg_format == "messages":
                response = self.response_as_dict(response)
            if (
                self.multimodal
                and isinstance(message, MultimodalData)
                and self.msg_format == "tuples"
            ):
                update = history + [[message.text, response]]
                yield update, update
            elif (
                self.multimodal
                and isinstance(message, MultimodalData)
                and self.msg_format == "messages"
            ):
                update = history + [
                    {"role": "user", "content": message.text},
                    response,
                ]
                yield update, update
            elif self.msg_format == "tuples":
                update = history + [[message, response]]
                yield update, update
            else:
                update = history + [{"role": "user", "content": message}, response]
                yield update, update

    async def _api_submit_fn(
        self,
        message: str,
        history: TupleFormat | list[MessageDict],
        request: Request,
        *args,
    ) -> tuple[str, TupleFormat | list[MessageDict]]:
        inputs, _, _ = special_args(
            self.fn, inputs=[message, history, *args], request=request
        )

        if self.is_async:
            response = await self.fn(*inputs)
        else:
            response = await anyio.to_thread.run_sync(
                self.fn, *inputs, limiter=self.limiter
            )
        if self.msg_format == "tuples":
            history.append([message, response])  # type: ignore
        else:
            new_response = self.response_as_dict(response)
            history.extend([{"role": "user", "content": message}, new_response])  # type: ignore
        return response, history

    async def _api_stream_fn(
        self, message: str, history: list[list[str | None]], request: Request, *args
    ) -> AsyncGenerator:
        inputs, _, _ = special_args(
            self.fn, inputs=[message, history, *args], request=request
        )
        if self.is_async:
            generator = self.fn(*inputs)
        else:
            generator = await anyio.to_thread.run_sync(
                self.fn, *inputs, limiter=self.limiter
            )
            generator = SyncToAsyncIterator(generator, self.limiter)
        try:
            first_response = await async_iteration(generator)
            if self.msg_format == "tuples":
                yield first_response, history + [[message, first_response]]
            else:
                first_response = self.response_as_dict(first_response)
                yield (
                    first_response,
                    history + [{"role": "user", "content": message}, first_response],
                )
        except StopIteration:
            yield None, history + [[message, None]]
        async for response in generator:
            if self.msg_format == "tuples":
                yield response, history + [[message, response]]
            else:
                new_response = self.response_as_dict(response)
                yield (
                    new_response,
                    history + [{"role": "user", "content": message}, new_response],
                )

    async def _examples_fn(
        self, message: str, *args
    ) -> TupleFormat | list[MessageDict]:
        inputs, _, _ = special_args(self.fn, inputs=[message, [], *args], request=None)

        if self.is_async:
            response = await self.fn(*inputs)
        else:
            response = await anyio.to_thread.run_sync(
                self.fn, *inputs, limiter=self.limiter
            )
        if self.msg_format == "tuples":
            return [[message, response]]
        else:
            return [{"role": "user", "content": message}, response]

    async def _examples_stream_fn(
        self,
        message: str,
        *args,
    ) -> AsyncGenerator:
        inputs, _, _ = special_args(self.fn, inputs=[message, [], *args], request=None)

        if self.is_async:
            generator = self.fn(*inputs)
        else:
            generator = await anyio.to_thread.run_sync(
                self.fn, *inputs, limiter=self.limiter
            )
            generator = SyncToAsyncIterator(generator, self.limiter)
        async for response in generator:
            if self.msg_format == "tuples":
                yield [[message, response]]
            else:
                new_response = self.response_as_dict(response)
                yield [{"role": "user", "content": message}, new_response]

    async def _delete_prev_fn(
        self,
        message: str | MultimodalData | None,
        history: list[MessageDict] | TupleFormat,
    ) -> tuple[
        list[MessageDict] | TupleFormat,
        str | MultimodalData,
        list[MessageDict] | TupleFormat,
    ]:
        extra = 1 if self.msg_format == "messages" else 0
        if self.multimodal and isinstance(message, MultimodalData):
            remove_input = (
                len(message.files) + 1
                if message.text is not None
                else len(message.files)
            ) + extra
            history = history[:-remove_input]
        else:
            history = history[: -(1 + extra)]
        return history, message or "", history
