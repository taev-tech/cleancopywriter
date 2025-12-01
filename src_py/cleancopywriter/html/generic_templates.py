from __future__ import annotations

from collections.abc import Sequence
from dataclasses import field
from typing import Annotated

from dcei import ext_dataclass
from docnote import Note
from templatey import Content
from templatey import DynamicClassSlot
from templatey import Slot
from templatey import TemplateClassInstance
from templatey import TemplateResourceConfig
from templatey import Var
from templatey.prebaked.configs import html
from templatey.prebaked.loaders import INLINE_TEMPLATE_LOADER

type HtmlTemplate = HtmlGenericElement | PlaintextTemplate


@ext_dataclass(
    html,
    TemplateResourceConfig(
        '<{content.tag}{slot.attrs: __prefix__=" "}>{slot.body}'
        + '</{content.tag}>',
        loader=INLINE_TEMPLATE_LOADER),
    kw_only=True)
class HtmlGenericElement:
    tag: Content[str]
    attrs: Slot[HtmlAttr] = field(default_factory=list)
    body: DynamicClassSlot


@ext_dataclass(
    html,
    TemplateResourceConfig(
        '{content.key}="{var.value}"', loader=INLINE_TEMPLATE_LOADER))
class HtmlAttr:
    key: Content[str]
    value: Var[str]


@ext_dataclass(
    html,
    TemplateResourceConfig('{var.text}', loader=INLINE_TEMPLATE_LOADER))
class PlaintextTemplate:
    text: Var[str]


def link_factory(
        body: Sequence[TemplateClassInstance],
        href: str,
        ) -> HtmlGenericElement:
    return HtmlGenericElement(
        tag='a',
        attrs=[HtmlAttr(key='href', value=href)],
        body=body)


def heading_factory(
        depth: Annotated[int, Note('Note: zero-indexed!')],
        body: Sequence[TemplateClassInstance]
        ) -> HtmlGenericElement:
    """Beyond what you'd expect, this:
    ++  converts a zero-indexed depth to a 1-indexed heading
    ++  clamps the value to the allowable HTML range [1, 6]
    """
    if depth < 0:
        heading_level = 1
    elif depth > 5:  # noqa: PLR2004
        heading_level = 6
    elif type(depth) is not int:
        heading_level = int(depth) + 1
    else:
        heading_level = depth + 1

    return HtmlGenericElement(
        tag=f'h{heading_level}',
        body=body)
