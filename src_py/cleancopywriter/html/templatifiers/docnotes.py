from __future__ import annotations

import typing
from collections.abc import Iterator
from collections.abc import Sequence
from dataclasses import field
from dataclasses import fields
from functools import singledispatch
from textwrap import dedent
from typing import Self
from typing import overload

from cleancopy.spectypes import InlineFormatting
from dcei import ext_dataclass
from dcei import ext_field
from docnote import MarkupLang
from docnote_extract.crossrefs import CallTraversal
from docnote_extract.crossrefs import Crossref
from docnote_extract.crossrefs import CrossrefTraversal
from docnote_extract.crossrefs import GetattrTraversal
from docnote_extract.crossrefs import GetitemTraversal
from docnote_extract.crossrefs import SyntacticTraversal
from docnote_extract.normalization import NormalizedConcreteType
from docnote_extract.normalization import NormalizedEmptyGenericType
from docnote_extract.normalization import NormalizedLiteralType
from docnote_extract.normalization import NormalizedSpecialType
from docnote_extract.normalization import NormalizedType
from docnote_extract.normalization import NormalizedUnionType
from docnote_extract.normalization import TypeSpec
from docnote_extract.summaries import CallableColor
from docnote_extract.summaries import CallableSummary
from docnote_extract.summaries import ClassSummary
from docnote_extract.summaries import CrossrefSummary
from docnote_extract.summaries import DocText
from docnote_extract.summaries import MethodType
from docnote_extract.summaries import ModuleSummary
from docnote_extract.summaries import NamespaceMemberSummary
from docnote_extract.summaries import ParamStyle
from docnote_extract.summaries import ParamSummary
from docnote_extract.summaries import RetvalSummary
from docnote_extract.summaries import SignatureSummary
from docnote_extract.summaries import SummaryBase
from docnote_extract.summaries import SummaryMetadataProtocol
from docnote_extract.summaries import VariableSummary
from templatey import Content
from templatey import DynamicClassSlot
from templatey import Slot
from templatey import TemplateResourceConfig
from templatey import Var
from templatey._types import TemplateClassInstance
from templatey.prebaked.configs import html
from templatey.prebaked.loaders import INLINE_TEMPLATE_LOADER
from templatey.templates import FieldConfig

from cleancopywriter.html.generic_templates import HtmlAttr
from cleancopywriter.html.generic_templates import HtmlGenericElement
from cleancopywriter.html.generic_templates import HtmlTemplate
from cleancopywriter.html.generic_templates import PlaintextTemplate
from cleancopywriter.html.templatifiers.clc import INLINE_PRE_CLASSNAME
from cleancopywriter.html.templatifiers.clc import ClcRichtextBlocknodeTemplate
from cleancopywriter.html.templatifiers.clc import formatting_factory

if typing.TYPE_CHECKING:
    from cleancopywriter.html.documents import HtmlDocumentCollection


@ext_dataclass(
    html,
    TemplateResourceConfig(
        # Note: we're not doing a role of list here, because the child elements
        # may or may not be list items (because they can also be used outside
        # of a literal) and therefore there's no way to distinguish between
        # them
        dedent('''\
            <docnote-fallback-container>
                {slot.wraps}
            </docnote-fallback-container>'''),
        loader=INLINE_TEMPLATE_LOADER))
class FallbackContainerTemplate:
    """Fallback templates are used for docnote things we haven't fully
    implemented yet, where we want to wrap a generic HTML element in
    a container.
    """
    wraps: Slot[HtmlGenericElement]


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <docnote-module role="article" {slot.plugin_attrs}>
                <docnote-header>
                    <docnote-name obj-type="module" role="heading" aria-level="1">
                        {var.fullname}
                    </docnote-name>
                    <docnote-docstring obj-type="module">
                        {slot.docstring}
                    </docnote-docstring>
                    <docnote-module-dunderall role="list">
                        {slot.dunder_all}
                    </docnote-module-dunderall>
                </docnote-header>
                {slot.members}
                <docnote-widgets>{slot.plugin_widgets}</docnote-widgets>
            </docnote-module>
            '''),  # noqa: E501
        loader=INLINE_TEMPLATE_LOADER))
class ModuleSummaryTemplate:
    fullname: Var[str]
    docstring: Slot[HtmlTemplate | ClcRichtextBlocknodeTemplate]
    dunder_all: Slot[HtmlGenericElement]
    # There's a bug somewhere in pyright that's saying ModuleSummaryTemplate
    # isn't actually a template params instance.
    members: Slot[NamespaceItemTemplate]  # type: ignore

    plugin_attrs: Slot[HtmlAttr]
    plugin_widgets: DynamicClassSlot

    @classmethod
    def from_summary(
            cls,
            summary_node: ModuleSummary,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        if summary_node.docstring is None:
            docstring = []
        else:
            docstring = templatify_doctext(
                summary_node.docstring, doc_coll, summary_node.metadata)

        if summary_node.dunder_all is None:
            dunder_all = []
        else:
            dunder_all = dunder_all_factory(sorted(summary_node.dunder_all))

        plugin_attrs, plugin_widgets = _apply_plugins(
            doc_coll, ModuleSummary, summary_node)
        return cls(
            fullname=summary_node.name,
            docstring=docstring,
            dunder_all=dunder_all,
            members=[
                get_template_cls(member).from_summary(member, doc_coll)  # type: ignore
                for member in cls.sort_members(summary_node.members)
                if should_include(member.metadata)],
            plugin_attrs=plugin_attrs,
            plugin_widgets=plugin_widgets)

    @classmethod
    def sort_members(
            cls,
            members: frozenset[NamespaceMemberSummary]
            ) -> list[NamespaceMemberSummary]:
        # TODO: this needs to support ordering index and groupings!
        return sorted(members, key=lambda member: member.name)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <docnote-attribute {slot.plugin_attrs}>
                <docnote-header>
                    <docnote-name obj-type="attribute" role="heading" aria-level="2">
                        {var.name}
                    </docnote-name>
                    {slot.typespec}
                </docnote-header>
                <docnote-notes>
                    {slot.notes}
                </docnote-notes>
                <docnote-widgets>{slot.plugin_widgets}</docnote-widgets>
            </docnote-attribute>
            '''),  # noqa: E501
        loader=INLINE_TEMPLATE_LOADER))
class VariableSummaryTemplate:
    name: Var[str]
    typespec: Slot[TypespecTemplate]
    notes: Slot[ClcRichtextBlocknodeTemplate | HtmlTemplate]

    plugin_attrs: Slot[HtmlAttr]
    plugin_widgets: DynamicClassSlot

    @classmethod
    def from_summary(
            cls,
            summary_node: VariableSummary,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        rendered_notes: list[ClcRichtextBlocknodeTemplate | HtmlTemplate] = []
        for note in summary_node.notes:
            rendered_notes.extend(
                templatify_doctext(
                    note, doc_coll, summary_node.metadata))

        plugin_attrs, plugin_widgets = _apply_plugins(
            doc_coll, VariableSummary, summary_node)
        return cls(
            name=summary_node.name,
            typespec=
                [templatify_typespec(summary_node.typespec)]
                if summary_node.typespec is not None
                else (),
            notes=rendered_notes,
            plugin_attrs=plugin_attrs,
            plugin_widgets=plugin_widgets)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <docnote-class {slot.plugin_attrs}>
                <docnote-header>
                    <docnote-name obj-type="class" role="heading" aria-level="2">
                        {var.name}
                    </docnote-name>
                    <docnote-class-metaclass>
                        {slot.metaclass}
                    </docnote-class-metaclass>
                    <docnote-class-bases-container>
                        <docnote-class-bases role="list">
                            {slot.bases:
                            __prefix__='<docnote-class-base role="listitem">',
                            __suffix__='</docnote-class-base>'}
                        </docnote-class-bases>
                    </docnote-class-bases-container>
                    <docnote-docstring obj-type="class">
                        {slot.docstring}
                    </docnote-docstring>
                </docnote-header>
                {slot.members}
                <docnote-widgets>{slot.plugin_widgets}</docnote-widgets>
            </docnote-class>
            '''),  # noqa: E501
        loader=INLINE_TEMPLATE_LOADER))
class ClassSummaryTemplate:
    name: Var[str]
    metaclass: Slot[NormalizedConcreteTypeTemplate]
    bases: Slot[NormalizedConcreteTypeTemplate]
    docstring: Slot[HtmlTemplate | ClcRichtextBlocknodeTemplate]
    # There's a bug somewhere in pyright that's saying ModuleSummaryTemplate
    # isn't actually a template params instance.
    members: Slot[NamespaceItemTemplate]  # type: ignore

    plugin_attrs: Slot[HtmlAttr]
    plugin_widgets: DynamicClassSlot

    @classmethod
    def from_summary(
            cls,
            summary_node: ClassSummary,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        if summary_node.docstring is None:
            docstring = []
        else:
            docstring = templatify_doctext(
                summary_node.docstring, doc_coll, summary_node.metadata)

        plugin_attrs, plugin_widgets = _apply_plugins(
            doc_coll, ClassSummary, summary_node)
        return cls(
            name=summary_node.name,
            metaclass=
                [templatify_concrete_typespec(summary_node.metaclass)]
                if summary_node.metaclass is not None
                else (),
            docstring=docstring,
            bases=[
                templatify_concrete_typespec(base)
                for base in summary_node.bases],
            members=[
                get_template_cls(member).from_summary(member, doc_coll)  # type: ignore
                for member in cls.sort_members(summary_node.members)
                if should_include(member.metadata)],
            plugin_attrs=plugin_attrs,
            plugin_widgets=plugin_widgets)

    @classmethod
    def sort_members(
            cls,
            members: frozenset[NamespaceMemberSummary]
            ) -> list[NamespaceMemberSummary]:
        # TODO: this needs to support ordering index and groupings!
        return sorted(members, key=lambda member: member.name)


def _transform_is_generator(value: bool) -> str:
    if value:
        return 'generator="true"'
    else:
        return 'generator="false"'


def _transform_method_type(value: MethodType | None) -> str:
    if value is MethodType.INSTANCE:
        return 'method-type="instancemethod"'
    elif value is MethodType.CLASS:
        return 'method-type="classmethod"'
    elif value is MethodType.STATIC:
        return 'method-type="staticmethod"'
    else:
        return 'method-type="null"'


def _transform_callable_color(value: CallableColor) -> str:
    if value is CallableColor.ASYNC:
        return 'call-color="async"'
    else:
        return 'call-color="sync"'


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <docnote-callable {slot.plugin_attrs}>
                <docnote-header>
                    <docnote-name obj-type="callable" role="heading" aria-level="2">
                        {var.name}
                    </docnote-name>
                    <docnote-docstring obj-type="callable">
                        {slot.docstring}
                    </docnote-docstring>
                    <docnote-tags>
                        <docnote-tag {content.color}></docnote-tag>
                        <docnote-tag {content.method_type}></docnote-tag>
                        <docnote-tag {content.is_generator}></docnote-tag>
                    </docnote-tags>
                </docnote-header>
                <docnote-callable-signatures>
                    {slot.signatures}
                </docnote-callable-signatures>
                <docnote-widgets>{slot.plugin_widgets}</docnote-widgets>
            </docnote-callable>
            '''),  # noqa: E501
        loader=INLINE_TEMPLATE_LOADER))
class CallableSummaryTemplate:
    name: Var[str]
    docstring: Slot[HtmlTemplate | ClcRichtextBlocknodeTemplate]

    color: Content[CallableColor] = ext_field(FieldConfig(
        transformer=_transform_callable_color))
    method_type: Content[MethodType | None] = ext_field(FieldConfig(
        transformer=_transform_method_type))
    is_generator: Content[bool] = ext_field(FieldConfig(
        transformer=_transform_is_generator))

    signatures: Slot[SignatureSummaryTemplate]

    plugin_attrs: Slot[HtmlAttr]
    plugin_widgets: DynamicClassSlot

    @classmethod
    def from_summary(
            cls,
            summary_node: CallableSummary,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        if summary_node.docstring is None:
            docstring = []
        else:
            docstring = templatify_doctext(
                summary_node.docstring, doc_coll, summary_node.metadata)

        plugin_attrs, plugin_widgets = _apply_plugins(
            doc_coll, CallableSummary, summary_node)
        return cls(
            name=summary_node.name,
            docstring=docstring,
            color=summary_node.color,
            method_type=summary_node.method_type,
            is_generator=summary_node.is_generator,
            signatures=[
                SignatureSummaryTemplate.from_summary(
                    signature, doc_coll)
                for signature in cls.sort_signatures(summary_node.signatures)
                if should_include(signature.metadata)],
            plugin_attrs=plugin_attrs,
            plugin_widgets=plugin_widgets)

    @classmethod
    def sort_signatures(
            cls,
            members: frozenset[SignatureSummary]
            ) -> list[SignatureSummary]:
        # TODO: this needs to support groupings, and we need to verify that
        # ordering index is always set on signature summaries!
        return sorted(members, key=lambda member: member.ordering_index or 0)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <docnote-callable-signature {slot.plugin_attrs}>
                <docnote-header>
                    <docnote-docstring obj-type="callable-signature">
                        {slot.docstring}
                    </docnote-docstring>
                </docnote-header>
                <docnote-callable-signature-params role="list">
                    {slot.params}
                </docnote-callable-signature-params>
                <docnote-callable-signature-retval>
                    {slot.retval}
                </docnote-callable-signature-retval>
                <docnote-widgets>{slot.plugin_widgets}</docnote-widgets>
            </docnote-callable-signature>
            '''),
        loader=INLINE_TEMPLATE_LOADER))
class SignatureSummaryTemplate:
    params: Slot[ParamSummaryTemplate]
    retval: Slot[RetvalSummaryTemplate]
    docstring: Slot[HtmlTemplate | ClcRichtextBlocknodeTemplate]

    plugin_attrs: Slot[HtmlAttr]
    plugin_widgets: DynamicClassSlot

    @classmethod
    def from_summary(
            cls,
            summary_node: SignatureSummary,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        if summary_node.docstring is None:
            docstring = []
        else:
            docstring = templatify_doctext(
                summary_node.docstring, doc_coll, summary_node.metadata)

        plugin_attrs, plugin_widgets = _apply_plugins(
            doc_coll, SignatureSummary, summary_node)
        return cls(
            params=[
                ParamSummaryTemplate.from_summary(param, doc_coll)
                for param in cls.sort_params(summary_node.params)
                if should_include(param.metadata)],
            retval=[
                RetvalSummaryTemplate.from_summary(
                    summary_node.retval, doc_coll)],
            docstring=docstring,
            plugin_attrs=plugin_attrs,
            plugin_widgets=plugin_widgets)

    @classmethod
    def sort_params(
            cls,
            members: frozenset[ParamSummary]
            ) -> list[ParamSummary]:
        # TODO: this needs to support groupings (probably just for kwarg-only
        # params though)
        return sorted(members, key=lambda member: member.index)


def _transform_param_style(value: ParamStyle) -> str:
    return f'style="{value.value}"'


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <docnote-callable-signature-param {content.style} role="listitem" {slot.plugin_attrs}>
                <docnote-header>
                    <docnote-name obj-type="callable-signature-param-item" role="heading" aria-level="3">
                        {var.name}
                    </docnote-name>
                    {slot.typespec}
                </docnote-header>
                <docnote-callable-signature-param-default>
                    {slot.default}
                </docnote-callable-signature-param-default>
                <docnote-notes>
                    {slot.notes}
                </docnote-notes>
                <docnote-widgets>{slot.plugin_widgets}</docnote-widgets>
            </docnote-callable-signature-param>
            '''),  # noqa: E501
        loader=INLINE_TEMPLATE_LOADER))
class ParamSummaryTemplate:
    style: Content[ParamStyle] = ext_field(FieldConfig(
        transformer=_transform_param_style))
    name: Var[str]
    typespec: Slot[TypespecTemplate]
    default: Slot[ValueReprTemplate]
    notes: Slot[HtmlTemplate | ClcRichtextBlocknodeTemplate]

    plugin_attrs: Slot[HtmlAttr]
    plugin_widgets: DynamicClassSlot

    @classmethod
    def from_summary(
            cls,
            summary_node: ParamSummary,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        rendered_notes: list[HtmlTemplate | ClcRichtextBlocknodeTemplate] = []
        for note in summary_node.notes:
            rendered_notes.extend(
                templatify_doctext(
                    note, doc_coll, summary_node.metadata))

        rendered_default: list[ValueReprTemplate] = []
        if summary_node.default is not None:
            rendered_default.append(
                ValueReprTemplate(repr(summary_node.default)))

        plugin_attrs, plugin_widgets = _apply_plugins(
            doc_coll, ParamSummary, summary_node)
        return cls(
            style=summary_node.style,
            name=summary_node.name,
            default=rendered_default,
            typespec=[templatify_typespec(summary_node.typespec)]
                if summary_node.typespec is not None
                else (),
            notes=rendered_notes,
            plugin_attrs=plugin_attrs,
            plugin_widgets=plugin_widgets)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        # Note: the parent signature is responsible for wrapping this in the
        # retval container tag.
        dedent('''\
            <docnote-header>
                {slot.typespec}
            </docnote-header>
            <docnote-notes>
                {slot.notes}
            </docnote-notes>
            '''),
        loader=INLINE_TEMPLATE_LOADER))
class RetvalSummaryTemplate:
    typespec: Slot[TypespecTemplate]
    notes: Slot[HtmlTemplate | ClcRichtextBlocknodeTemplate]

    @classmethod
    def from_summary(
            cls,
            summary_node: RetvalSummary,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        rendered_notes: list[HtmlTemplate | ClcRichtextBlocknodeTemplate] = []
        for note in summary_node.notes:
            rendered_notes.extend(
                templatify_doctext(
                    note, doc_coll, summary_node.metadata))

        return cls(
            typespec=[templatify_typespec(summary_node.typespec)]
                if summary_node.typespec is not None
                else (),
            notes=rendered_notes)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <docnote-value-repr>
                {var.reprified_value}
            </docnote-value-repr>
            '''),
        loader=INLINE_TEMPLATE_LOADER))
class ValueReprTemplate:
    reprified_value: Var[str]


type NormalizedTypeTemplate = (
    NormalizedUnionTypeTemplate
    | NormalizedEmptyGenericTypeTemplate
    | NormalizedConcreteTypeTemplate
    | NormalizedSpecialTypeTemplate
    | NormalizedLiteralTypeTemplate)


def _transform_lowercase_bool(value: bool) -> str:
    if value:
        return 'true'
    else:
        return 'false'


def _transform_tagspec_key(value: str) -> str:
    return value.removeprefix('has_')


@ext_dataclass(
    html,
    TemplateResourceConfig(
        '<docnote-tag {content.key}="{content.value}"></docnote-tag>',
        loader=INLINE_TEMPLATE_LOADER))
class TypespecTagTemplate:
    """Typespec tags are used for eg ``ClassVar[...]``, ``Final[...]``,
    etc.
    """
    key: Content[str] = ext_field(
        FieldConfig(transformer=_transform_tagspec_key))
    value: Content[bool] = ext_field(
        FieldConfig(transformer=_transform_lowercase_bool))


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <docnote-typespec>
                <docnote-normtype>
                    {slot.normtype}
                </docnote-normtype>
                <docnote-tags>
                    {slot.typespec_tags}
                </docnote-tags>
            </docnote-typespec>'''),
        loader=INLINE_TEMPLATE_LOADER))
class TypespecTemplate:
    normtype: Slot[NormalizedTypeTemplate]
    typespec_tags: Slot[TypespecTagTemplate]


@ext_dataclass(
    html,
    TemplateResourceConfig(
        # Note: we're not doing a role of list here, because the child elements
        # may or may not be list items (because they can also be used outside
        # of a union) and therefore there's no way to distinguish between them
        dedent('''\
            <docnote-normtype-union-container>
                <docnote-normtype-union>
                    {slot.normtypes}
                </docnote-normtype-union>
            </docnote-normtype-union-container>'''),
        loader=INLINE_TEMPLATE_LOADER))
class NormalizedUnionTypeTemplate:
    normtypes: Slot[NormalizedTypeTemplate]


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <docnote-normtype-concrete>
                <docnote-normtype-concrete-primary>
                    {slot.primary}
                </docnote-normtype-concrete-primary>
                <docnote-normtype-params-container>
                    <docnote-normtype-params>
                        {slot.params}
                    </docnote-normtype-params>
                </docnote-normtype-params-container>
            </docnote-normtype-concrete>'''),
        loader=INLINE_TEMPLATE_LOADER))
class NormalizedConcreteTypeTemplate:
    primary: Slot[CrossrefSummaryTemplate]
    params: Slot[NormalizedTypeTemplate]


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <docnote-normtype-emptygeneric>
                <docnote-normtype-params-container>
                    <docnote-normtype-params>
                        {slot.params}
                    </docnote-normtype-params>
                </docnote-normtype-params-container>
            </docnote-normtype-emptygeneric>'''),
        loader=INLINE_TEMPLATE_LOADER))
class NormalizedEmptyGenericTypeTemplate:
    params: Slot[NormalizedTypeTemplate]


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <docnote-normtype-specialform>
                {slot.type_}
            </docnote-normtype-specialform>'''),
        loader=INLINE_TEMPLATE_LOADER))
class NormalizedSpecialTypeTemplate:
    type_: Slot[CrossrefSummaryTemplate]


@ext_dataclass(
    html,
    TemplateResourceConfig(
        # Note: we're not doing a role of list here, because the child elements
        # may or may not be list items (because they can also be used outside
        # of a literal) and therefore there's no way to distinguish between
        # them
        dedent('''\
            <docnote-normtype-literal>
                {slot.values}
            </docnote-normtype-literal>'''),
        loader=INLINE_TEMPLATE_LOADER))
class NormalizedLiteralTypeTemplate:
    values: Slot[FallbackContainerTemplate | CrossrefSummaryTemplate]


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <abbr title="{var.qualname}{var.traversals}">
                {slot.crossref_target}
            </abbr>
            '''),
        loader=INLINE_TEMPLATE_LOADER))
class CrossrefSummaryTemplate:
    qualname: Var[str]
    traversals: Var[str | None] = field(default=None, kw_only=True)
    crossref_target: Slot[CrossrefLinkTemplate | CrossrefTextTemplate]

    @classmethod
    def from_crossref(cls, crossref: Crossref) -> Self:
        if crossref.toplevel_name is None:
            shortname = qualname = f'<Module {crossref.module_name}>'
        else:
            # These are actually unknown in case of traversals...
            # TODO: that needs fixing! probably with <> brackets.
            shortname = crossref.toplevel_name
            qualname = f'{crossref.module_name}:{crossref.toplevel_name}'

        traversals = (''.join(
            _flatten_typespec_traversals(crossref.traversals))
            if crossref.traversals else None)

        # TODO: we need to convert the slot to be an environment function
        # operating on the document collection so that linkability can be
        # determined lazily at render time
        return cls(
            qualname=qualname,
            traversals=traversals,
            crossref_target=[
                CrossrefTextTemplate(
                    shortname=shortname,
                    has_traversals=traversals is not None)])

    @classmethod
    def from_summary(
            cls,
            summary_node: CrossrefSummary,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        if summary_node.crossref is None:
            raise ValueError('Cannot templatify a nonexistent crossref!')

        return cls.from_crossref(summary_node.crossref)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        '<a href="{var.target}">{slot.text}</a>',
        loader=INLINE_TEMPLATE_LOADER))
class CrossrefLinkTemplate:
    target: Var[str]
    text: Slot[CrossrefTextTemplate]

    has_traversals: bool = field(init=False)

    def __post_init__(self):
        for text_instance in self.text:
            text_instance.has_traversals = self.has_traversals


@ext_dataclass(
    html,
    TemplateResourceConfig(
        '{var.shortname}{content.has_traversals}',
        loader=INLINE_TEMPLATE_LOADER))
class CrossrefTextTemplate:
    shortname: Var[str]
    has_traversals: Content[bool] = ext_field(
        FieldConfig(
            transformer=lambda value: '<...>' if value else None))


def templatify_doctext(
        doctext: DocText,
        doc_coll: HtmlDocumentCollection,
        summary_metadata: SummaryMetadataProtocol,
        ) -> list[HtmlTemplate | ClcRichtextBlocknodeTemplate]:
    if doctext.markup_lang is None:
        return [
            HtmlGenericElement(
                tag='code',
                body=[PlaintextTemplate(doctext.value)],
                attrs=[HtmlAttr(key='class', value=INLINE_PRE_CLASSNAME)])]

    if isinstance(doctext.markup_lang, str):
        if doctext.markup_lang in set(MarkupLang.CLEANCOPY.value):
            markup_lang = MarkupLang.CLEANCOPY
        else:
            markup_lang = None
    else:
        markup_lang = doctext.markup_lang

    if markup_lang is not MarkupLang.CLEANCOPY:
        raise ValueError(
            'Unsupported markup language for doctext!', doctext)

    ast_doc = doc_coll.preprocess(
        clc_text=doctext.value,
        context=summary_metadata)
    return [ClcRichtextBlocknodeTemplate.from_document(
        ast_doc, doc_coll=doc_coll)]


def templatify_concrete_typespec(
        typespec: TypeSpec
        ) -> NormalizedConcreteTypeTemplate:
    """Use this to render the (concrete, ie, cannot be a union etc)
    typespec -- ie, metaclasses and base classes.
    """
    result = templatify_normalized_type(typespec.normtype)
    if not isinstance(result, NormalizedConcreteTypeTemplate):
        raise TypeError(
            'Invalid concrete type (metaclass or base)', typespec)

    return result


def templatify_typespec(
        typespec: TypeSpec
        ) -> TypespecTemplate:
    tags: list[TypespecTagTemplate] = []

    for dc_field in fields(typespec):
        if dc_field.name != 'normtype':
            tags.append(TypespecTagTemplate(
                key=dc_field.name,
                value=getattr(typespec, dc_field.name)))

    return TypespecTemplate(
        normtype=[templatify_normalized_type(typespec.normtype)],
        typespec_tags=tags)


@singledispatch
def templatify_normalized_type(
        normtype: NormalizedType
        ) -> NormalizedTypeTemplate:
    raise TypeError('Unknown normalized type!', normtype)

@templatify_normalized_type.register
def _(
        normtype: NormalizedUnionType
        ) -> NormalizedUnionTypeTemplate:
    return NormalizedUnionTypeTemplate(
        normtypes=[
            templatify_normalized_type(nested_normtype)
            for nested_normtype in normtype.normtypes])

@templatify_normalized_type.register
def _(
        normtype: NormalizedEmptyGenericType
        ) -> NormalizedEmptyGenericTypeTemplate:
    return NormalizedEmptyGenericTypeTemplate(
        params=[
            templatify_normalized_type(param_typespec.normtype)
            for param_typespec in normtype.params])

@templatify_normalized_type.register
def _(
        normtype: NormalizedConcreteType
        ) -> NormalizedConcreteTypeTemplate:
    return NormalizedConcreteTypeTemplate(
        primary=[CrossrefSummaryTemplate.from_crossref(normtype.primary)],
        params=[
            templatify_normalized_type(param_typespec.normtype)
            for param_typespec in normtype.params])

@templatify_normalized_type.register
def _(
        normtype: NormalizedSpecialType
        ) -> NormalizedSpecialTypeTemplate:
    return NormalizedSpecialTypeTemplate(
        type_=[specialform_type_factory(normtype)])

@templatify_normalized_type.register
def _(
        normtype: NormalizedLiteralType
        ) -> NormalizedLiteralTypeTemplate:
    return NormalizedLiteralTypeTemplate(
        values=[
            literal_value_factory(value)
            for value in normtype.values])


@overload
def get_template_cls(
        summary: ModuleSummary
        ) -> type[ModuleSummaryTemplate]: ...
@overload
def get_template_cls(
        summary: VariableSummary
        ) -> type[VariableSummaryTemplate]: ...
@overload
def get_template_cls(
        summary: ClassSummary
        ) -> type[ClassSummaryTemplate]: ...
@overload
def get_template_cls(
        summary: CallableSummary
        ) -> type[CallableSummaryTemplate]: ...
@overload
def get_template_cls(
        summary: CrossrefSummary
        ) -> type[CrossrefSummaryTemplate]: ...
def get_template_cls(
        summary:
            ModuleSummary
            | VariableSummary
            | ClassSummary
            | CallableSummary
            | CrossrefSummary
        ) -> (
            type[ModuleSummaryTemplate]
            | type[VariableSummaryTemplate]
            | type[ClassSummaryTemplate]
            | type[CallableSummaryTemplate]
            | type[CrossrefSummaryTemplate]
        ):
    """Gets the appropriate template class for the passed summary
    object. Only supports objects that can be contained within a
    namespace; the rest should be known directly based on the structure
    of the summary.
    """
    if isinstance(summary, ModuleSummary):
        return ModuleSummaryTemplate
    elif isinstance(summary, VariableSummary):
        return VariableSummaryTemplate
    elif isinstance(summary, ClassSummary):
        return ClassSummaryTemplate
    elif isinstance(summary, CallableSummary):
        return CallableSummaryTemplate
    elif isinstance(summary, CrossrefSummary):
        return CrossrefSummaryTemplate
    else:
        raise TypeError('Unsupported summary type', summary)


def should_include(
        metadata: SummaryMetadataProtocol
        ) -> bool:
    if metadata.extracted_inclusion is True:
        return True
    if metadata.extracted_inclusion is False:
        return False

    return metadata.to_document and not metadata.disowned


def _flatten_typespec_traversals(
        traversals: Sequence[CrossrefTraversal],
        *,
        _index=0
        ) -> Iterator[str]:
    """This is a backstop to collapse crossref traversals into a string
    that can be rendered.
    """
    if len(traversals) <= _index:
        return

    this_traversal = traversals[_index]

    if isinstance(this_traversal, GetattrTraversal):
        yield f'.{this_traversal.name}'

    elif isinstance(this_traversal, CallTraversal):
        yield f'(*{this_traversal.args}, **{this_traversal.kwargs})'

    elif isinstance(this_traversal, GetitemTraversal):
        yield f'[{this_traversal.key}]'

    elif isinstance(this_traversal, SyntacticTraversal):
        yield f'<{this_traversal.type_.value}: {this_traversal.key}>'

    else:
        raise TypeError('Invalid traversal type for typespec!', this_traversal)

    yield from _flatten_typespec_traversals(traversals, _index=_index + 1)


def dunder_all_factory(
        names: Sequence[str],
        ) -> list[HtmlGenericElement]:
    retval: list[HtmlGenericElement] = []
    for name in names:
        retval.append(HtmlGenericElement(
            tag='li',
            body=[PlaintextTemplate(name)]))

    return retval


_specialform_lookup: dict[NormalizedSpecialType, CrossrefSummaryTemplate] = {
    NormalizedSpecialType.ANY: CrossrefSummaryTemplate(
            qualname='typing.Any',
            crossref_target=[
                CrossrefTextTemplate(
                    shortname='Any',
                    has_traversals=False)]),
    NormalizedSpecialType.LITERAL_STRING: CrossrefSummaryTemplate(
            qualname='typing.LiteralString',
            crossref_target=[
                CrossrefTextTemplate(
                    shortname='LiteralString',
                    has_traversals=False)]),
    NormalizedSpecialType.NEVER: CrossrefSummaryTemplate(
            qualname='typing.Never',
            crossref_target=[
                CrossrefTextTemplate(
                    shortname='Never',
                    has_traversals=False)]),
    NormalizedSpecialType.NORETURN: CrossrefSummaryTemplate(
            qualname='typing.NoReturn',
            crossref_target=[
                CrossrefTextTemplate(
                    shortname='NoReturn',
                    has_traversals=False)]),
    NormalizedSpecialType.SELF: CrossrefSummaryTemplate(
            qualname='typing.Self',
            crossref_target=[
                CrossrefTextTemplate(
                    shortname='Self',
                    has_traversals=False)]),
    NormalizedSpecialType.NONE: CrossrefSummaryTemplate(
            qualname='builtins.None',
            crossref_target=[
                CrossrefTextTemplate(
                    shortname='None',
                    has_traversals=False)]),
}


def specialform_type_factory(
        normtype: NormalizedSpecialType
        ) -> CrossrefSummaryTemplate:
    return _specialform_lookup[normtype]


def literal_value_factory(
        value: int | bool | str | bytes | Crossref
        ) -> FallbackContainerTemplate | CrossrefSummaryTemplate:
    if isinstance(value, Crossref):
        if value.module_name is None:
            raise ValueError(
                'Crossreffed literal values can only be enums; module name '
                + 'is required!', value)
        if value.toplevel_name is None:
            raise ValueError(
                'Crossreffed literal values can only be enums; toplevel name '
                + 'is required!', value)
        if (
            len(value.traversals) != 1
            or not isinstance(value.traversals[0], GetattrTraversal)
        ):
            raise ValueError(
                'Crossreffed literal values can only be enums; must have '
                + 'exactly one ``GetattrTraversal``!', value)

        return CrossrefSummaryTemplate.from_crossref(value)

    return FallbackContainerTemplate(
        wraps=[formatting_factory(
            spectype=InlineFormatting.PRE,
            body=[PlaintextTemplate(repr(value))])])


# This was running into pyright bugs when being used as a template class;
# we're putting it at the end of the file in the hopes of fixing them by
# changing the order of forward refs
type NamespaceItemTemplate = (
    ModuleSummaryTemplate
    | VariableSummaryTemplate
    | ClassSummaryTemplate
    | CallableSummaryTemplate)


def _apply_plugins[T: SummaryBase](
        doc_coll: HtmlDocumentCollection,
        summary_type: type[T],
        summary: T
        ) -> tuple[list[HtmlAttr], list[TemplateClassInstance]]:
    plugins = doc_coll.plugin_manager.get_docnotes_plugins(summary_type)
    plugin_attrs: list[HtmlAttr] = []
    plugin_widgets: list[TemplateClassInstance] = []

    for plugin in plugins:
        injection = plugin(summary)
        if injection is not None:
            if injection.attrs is not None:
                plugin_attrs.extend(injection.attrs)
            if injection.widgets is not None:
                plugin_widgets.extend(injection.widgets)

    return plugin_attrs, plugin_widgets
