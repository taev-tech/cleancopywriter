from __future__ import annotations

import typing
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from html import escape as html_escape
from textwrap import dedent
from typing import Self
from typing import cast

from cleancopy.ast import Annotation
from cleancopy.ast import ASTNode
from cleancopy.ast import BlockNodeInfo
from cleancopy.ast import BoolDataType
from cleancopy.ast import DecimalDataType
from cleancopy.ast import Document as ClcDocument
from cleancopy.ast import EmbeddingBlockNode
from cleancopy.ast import InlineNodeInfo
from cleancopy.ast import IntDataType
from cleancopy.ast import List_
from cleancopy.ast import ListItem
from cleancopy.ast import MentionDataType
from cleancopy.ast import NodeInfo
from cleancopy.ast import NullDataType
from cleancopy.ast import Paragraph
from cleancopy.ast import ReferenceDataType
from cleancopy.ast import RichtextBlockNode
from cleancopy.ast import RichtextInlineNode
from cleancopy.ast import StrDataType
from cleancopy.ast import TagDataType
from cleancopy.ast import VariableDataType
from cleancopy.spectypes import BlockFormatting
from cleancopy.spectypes import BlockMetadataMagic
from cleancopy.spectypes import InlineFormatting
from cleancopy.spectypes import InlineMetadataMagic
from cleancopy.spectypes import ListType
from dcei import ext_dataclass
from dcei import ext_field
from templatey import Content
from templatey import DynamicClassSlot
from templatey import Slot
from templatey import TemplateClassInstance
from templatey import TemplateResourceConfig
from templatey import Var
from templatey.prebaked.configs import html
from templatey.prebaked.loaders import INLINE_TEMPLATE_LOADER
from templatey.templates import FieldConfig
from templatey.templates import InjectedValue

from cleancopywriter.html.generic_templates import HtmlAttr
from cleancopywriter.html.generic_templates import HtmlGenericElement
from cleancopywriter.html.generic_templates import HtmlTemplate
from cleancopywriter.html.generic_templates import PlaintextTemplate
from cleancopywriter.html.generic_templates import heading_factory

if typing.TYPE_CHECKING:
    from cleancopywriter.html.documents import HtmlDocumentCollection
else:
    # We do this to make the @singledispatch work at runtime even though the
    # document collection isn't defined
    HtmlDocumentCollection = object

INLINE_PRE_CLASSNAME = 'clc-fmt-pre'
UNDERLINE_TAGNAME = 'clc-ul'
DATATYPE_NAMES = {
    StrDataType: 'str',
    IntDataType: 'int',
    DecimalDataType: 'dec',
    BoolDataType: 'bool',
    NullDataType: 'null',
    MentionDataType: '@',
    TagDataType: '#',
    VariableDataType: '%',
    ReferenceDataType: '&',}


def _transform_spec_metadatas_block(
        value: BlockNodeInfo,
        doc_coll: HtmlDocumentCollection
        ) -> list[HtmlAttr]:
    retval: list[HtmlAttr] = []
    for enum_member in BlockMetadataMagic:
        fieldname = enum_member.name

        # Skip is_doc_metadata because it's only relevant for creating the AST
        # Skip the other because it's handled by the actual processing code
        if fieldname in {'is_doc_metadata', 'semantic_modifiers'}:
            continue

        field_value = getattr(value, fieldname)
        if field_value is not None:
            # These are both enums that need special handling, but the value
            # itself is already safe (since we control it)
            if fieldname in {'formatting', 'fallback'}:
                coerced_fieldname = fieldname
                coerced_field_value = field_value.name.lower()

            else:
                if fieldname == 'embed':
                    coerced_fieldname = 'embedding'
                elif fieldname == 'style_modifiers':
                    coerced_fieldname = 'class'
                else:
                    coerced_fieldname = fieldname.replace('_', '-')

                if isinstance(
                    field_value,
                    MentionDataType
                    | TagDataType
                    | VariableDataType
                    | ReferenceDataType
                ):
                    coerced_field_value = doc_coll.target_resolver(field_value)
                else:
                    coerced_field_value = html_escape(
                        field_value.value, quote=True)

            retval.append(HtmlAttr(coerced_fieldname, coerced_field_value))

    retval.sort(key=lambda instance: instance.key)
    return retval


def _transform_spec_metadatas_inline(
        value: InlineNodeInfo,
        doc_coll: HtmlDocumentCollection
        ) -> list[HtmlAttr]:
    retval: list[HtmlAttr] = []
    for enum_member in InlineMetadataMagic:
        fieldname = enum_member.name

        # Skip these because they're handled by the actual processing code
        if fieldname in {
            'formatting',
            'sugared',
            'semantic_modifiers',
        }:
            continue

        field_value = getattr(value, fieldname)
        if field_value is not None:
            if fieldname == 'style_modifiers':
                coerced_fieldname = 'class'
            else:
                coerced_fieldname = fieldname.replace('_', '-')

            if isinstance(
                field_value,
                MentionDataType
                | TagDataType
                | VariableDataType
                | ReferenceDataType
            ):
                coerced_field_value = doc_coll.target_resolver(field_value)
            else:
                coerced_field_value = html_escape(
                    field_value.value, quote=True)

            retval.append(HtmlAttr(coerced_fieldname, coerced_field_value))

    retval.sort(key=lambda instance: instance.key)
    return retval


@ext_dataclass(
    html,
    TemplateResourceConfig(
        '<clc-metadata type="{content.type_}" key="{var.key}" '
        + 'value="{var.value}"{slot.extra_attrs: __prefix__=" "}>'
        + '</clc-metadata>',
        loader=INLINE_TEMPLATE_LOADER))
class ClcMetadataTemplate:
    """This template is used for individual metadata key/value pairs.
    """
    type_: Content[str]
    key: Var[object]
    value: Var[object]
    extra_attrs: Slot[HtmlAttr] = field(default_factory=tuple)

    @classmethod
    def from_ast_node(
            cls,
            node: NodeInfo,
            doc_coll: HtmlDocumentCollection
            ) -> list[Self]:
        retval: list[Self] = []
        for key, datatyped_value in node.metadata.items():
            # Special-case the null so that we can use an empty string for the
            # value instead of ``None``
            if isinstance(datatyped_value, NullDataType):
                retval.append(cls(
                    type_=DATATYPE_NAMES[type(datatyped_value)],
                    key=key,
                    value=''))

            else:
                # And special-case the dedicated reference types, so that they
                # can be given both the raw value and the resolved one.
                if isinstance(
                    datatyped_value,
                    MentionDataType
                    | TagDataType
                    | VariableDataType
                    | ReferenceDataType
                ):
                    href = doc_coll.target_resolver(datatyped_value)
                    extra_attrs = [HtmlAttr('href', href)]

                else:
                    extra_attrs = ()

                retval.append(cls(
                    type_=DATATYPE_NAMES[type(datatyped_value)],
                    key=key,
                    value=html_escape(str(datatyped_value.value), quote=True),
                    extra_attrs=extra_attrs))

        return retval


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <clc-block type="richtext"{
                    slot.spectype_attrs: __prefix__=' '}{
                    slot.plugin_attrs: __prefix__=' '}>{
                slot.metadata:
                    __header__="\\n<clc-metadatas>",
                    __prefix__="\\n",
                    __footer__="\\n</clc-metadatas>"}
                {@wrap_node_start(data.tag_wrappers)
                }<clc-header>{slot.title}</clc-header>
                {slot.body}{
                slot.plugin_widgets:
                    __header__="\\n<clc-widgets>",
                    __prefix__="\\n",
                    __footer__="\\n</clc-widgets>"}{
                @wrap_node_end(data.tag_wrappers)}
            </clc-block>'''),
        loader=INLINE_TEMPLATE_LOADER))
class ClcRichtextBlocknodeTemplate:
    """This template is used for richtext block nodes. Note that it
    differs (only slightly) from the template used for embedding block
    nodes.
    """
    tag_wrappers: list[NodeContentTagWrapper] = field(
        kw_only=True, default_factory=list)

    title: Slot[HtmlGenericElement]
    metadata: Slot[ClcMetadataTemplate]
    body: Slot[
        ClcParagraphTemplate
        | ClcEmbeddingBlocknodeTemplate
        | ClcRichtextBlocknodeTemplate]

    plugin_attrs: Slot[HtmlAttr]
    plugin_widgets: DynamicClassSlot

    spectype_attrs: Slot[HtmlAttr]

    @classmethod
    def from_document(
            cls,
            node: ClcDocument | RichtextBlockNode,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        """Constructs a document template from an AST document. This is
        a compatibility shim for when cleancopy documents were always
        wrapped in an outer ``Document`` object instead of exposing the
        root node directly.
        """
        # This is a preemptive backwards-compatibility shim
        if isinstance(node, ClcDocument):
            template_instance = cls.from_ast_node(node.root, doc_coll)

            # The only real compatibility issue is that we need to use the
            # metadata from the document object instead of the node object
            # (but only if metadata is actually defined there)
            if node.info is not None:
                template_instance.metadata = ClcMetadataTemplate.from_ast_node(
                    node.info, doc_coll)

        else:
            template_instance = cls.from_ast_node(node, doc_coll)

        return template_instance

    @classmethod
    def from_ast_node(
            cls,
            node: RichtextBlockNode,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        if node.title is None:
            title = []
        else:
            title = [heading_factory(
                depth=node.depth,
                body=[ClcRichtextInlineNodeTemplate.from_ast_node(
                        node.title, doc_coll)])]

        templatified_content = []
        for paragraph_or_node in node.content:
            if isinstance(paragraph_or_node, Paragraph):
                templatified_content.append(
                    ClcParagraphTemplate.from_ast_node(
                        paragraph_or_node, doc_coll))

            elif isinstance(paragraph_or_node, EmbeddingBlockNode):
                templatified_content.append(
                    ClcEmbeddingBlocknodeTemplate.from_ast_node(
                        paragraph_or_node, doc_coll))

            elif isinstance(paragraph_or_node, RichtextBlockNode):
                templatified_content.append(
                    ClcRichtextBlocknodeTemplate.from_ast_node(
                        paragraph_or_node, doc_coll))

            else:
                raise TypeError(
                    'Invalid child of richtext blocknode!', paragraph_or_node)

        plugin_attrs, plugin_widgets = _apply_plugins(
            doc_coll, RichtextBlockNode, node)

        if node.info is None:
            spectype_attrs = ()
            tag_wrappers = []
        else:
            tag_wrappers = _derive_blocknode_tag_wrappers(
                cast(BlockNodeInfo, node.info), doc_coll=doc_coll)

            spectype_attrs = _transform_spec_metadatas_block(
                node.info,
                doc_coll=doc_coll)

        return cls(
            title=title,
            tag_wrappers=tag_wrappers,
            metadata=ClcMetadataTemplate.from_ast_node(
                node.info, doc_coll) if node.info is not None else [],
            body=templatified_content,
            spectype_attrs=spectype_attrs,
            plugin_attrs=plugin_attrs,
            plugin_widgets=plugin_widgets)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        '<clc-embedding-fallback><pre>{slot.body}</pre>'
        + '</clc-embedding-fallback>',
        loader=INLINE_TEMPLATE_LOADER))
class ClcEmbeddingFallbackContentTemplate:
    """This template is used as a fallback for embeddings where there is
    no plugin defined to handle the embedding type.
    """
    body: Slot[PlaintextTemplate]


@ext_dataclass(
    html,
    TemplateResourceConfig(
        '<clc-embedding-plugin plugin-name="{content.plugin_name}">{slot.body}'
        + '</clc-embedding-plugin>',
        loader=INLINE_TEMPLATE_LOADER))
class ClcEmbeddingPluginContentTemplate:
    """This template is used for embeddings where a plugin is defined to
    handle the embedding type.
    """
    plugin_name: Content[str]
    body: DynamicClassSlot


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <clc-block type="embedding"{
                    slot.spectype_attrs: __prefix__=' '}{
                    slot.plugin_attrs: __prefix__=' '}>{
                slot.metadata:
                    __header__="\\n<clc-metadatas>",
                    __prefix__="\\n",
                    __footer__="\\n</clc-metadatas>"}
                {@wrap_node_start(data.tag_wrappers)
                }<clc-header>{slot.title}</clc-header>
                {slot.embedding_content}{
                slot.plugin_widgets:
                    __header__="\\n<clc-widgets>",
                    __prefix__="\\n",
                    __footer__="\\n</clc-widgets>"}{
                @wrap_node_end(data.tag_wrappers)}
            </clc-block>'''),
        loader=INLINE_TEMPLATE_LOADER))
class ClcEmbeddingBlocknodeTemplate:
    """This template is used to contain embedding block
    nodes. Note that it differs (only slightly) from the template used
    for richtext block nodes.
    """
    tag_wrappers: list[NodeContentTagWrapper] = field(
        kw_only=True, default_factory=list)

    title: Slot[HtmlGenericElement]
    metadata: Slot[ClcMetadataTemplate]
    embedding_content: Slot[
        ClcEmbeddingFallbackContentTemplate
        | ClcEmbeddingPluginContentTemplate]

    plugin_attrs: Slot[HtmlAttr]
    # Note: this isn't necessarily redundant, because you might have a global
    # widget system that modifies every node, independently of the actual
    # embedding system.
    plugin_widgets: DynamicClassSlot

    spectype_attrs: Slot[HtmlAttr]

    @classmethod
    def from_ast_node(  # noqa: PLR0912
            cls,
            node: EmbeddingBlockNode,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        if node.title is None:
            title = []
        else:
            title = [heading_factory(
                depth=node.depth,
                body=[ClcRichtextInlineNodeTemplate.from_ast_node(
                        node.title, doc_coll)])]

        plugin_attrs, plugin_widgets = _apply_plugins(
            doc_coll, EmbeddingBlockNode, node)

        if node.info is None:
            raise TypeError(
                'Impossible branch: embedding block node without nodeinfo!',
                node)
        if node.info.embed is None:
            raise TypeError(
                'Impossible branch: embedding block node with null '
                + 'nodeinfo.embed!', node)

        embedding_content: list[
            ClcEmbeddingFallbackContentTemplate
            | ClcEmbeddingPluginContentTemplate] = []
        embedding_type = node.info.embed.value
        embeddings_plugins = doc_coll.plugin_manager.get_embeddings_plugins(
            embedding_type)
        for embeddings_plugin in embeddings_plugins:
            plugin_injection = embeddings_plugin(node, embedding_type)
            if plugin_injection is not None:
                if plugin_injection.widgets is None:
                    injection_body = []
                else:
                    injection_body = plugin_injection.widgets

                embedding_content.append(
                    ClcEmbeddingPluginContentTemplate(
                        plugin_name=embeddings_plugin.plugin_name,
                        body=injection_body))

                if plugin_injection.attrs is not None:
                    plugin_attrs.extend(plugin_injection.attrs)

                break

        else:
            if node.content is None:
                plaintext_body = []
            else:
                plaintext_body = [PlaintextTemplate(text=node.content)]

            embedding_content.append(ClcEmbeddingFallbackContentTemplate(
                body=plaintext_body))

        if node.info is None:
            spectype_attrs = ()
            tag_wrappers = []
        else:
            tag_wrappers = _derive_blocknode_tag_wrappers(
                cast(BlockNodeInfo, node.info), doc_coll=doc_coll)

            spectype_attrs = _transform_spec_metadatas_block(
                node.info,
                doc_coll=doc_coll)

        return cls(
            title=title,
            metadata=ClcMetadataTemplate.from_ast_node(node.info, doc_coll),
            embedding_content=embedding_content,
            spectype_attrs=spectype_attrs,
            plugin_attrs=plugin_attrs,
            tag_wrappers=tag_wrappers,
            plugin_widgets=plugin_widgets)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <clc-context{slot.spectype_attrs: __prefix__=' '}{
                    slot.plugin_attrs: __prefix__=' '}>{
                slot.metadata:
                    __header__="\\n<clc-metadatas>",
                    __prefix__="\\n",
                    __footer__="\\n</clc-metadatas>"}
                {@wrap_node_start(data.tag_wrappers)
                }{slot.body}{
                slot.plugin_widgets:
                    __header__="\\n<clc-widgets>",
                    __prefix__="\\n",
                    __footer__="\\n</clc-widgets>"}{
                @wrap_node_end(data.tag_wrappers)}
            </clc-context>'''),
        loader=INLINE_TEMPLATE_LOADER))
class ClcRichtextInlineNodeTemplate:
    """This is used as the outermost wrapper for inline richtext nodes.
    Note that all text is wrapped in one of these -- including text
    within titles -- and therefore a ``<p>`` tag cannot be used (because
    they aren't valid within ``<h#>`` tags).
    """
    tag_wrappers: list[NodeContentTagWrapper] = field(
        kw_only=True, default_factory=list)

    metadata: Slot[ClcMetadataTemplate]
    body: Slot[HtmlTemplate | ClcRichtextInlineNodeTemplate]  # type: ignore

    plugin_attrs: Slot[HtmlAttr]
    plugin_widgets: DynamicClassSlot

    spectype_attrs: Slot[HtmlAttr]

    @classmethod
    def from_ast_node(
            cls,
            node: RichtextInlineNode,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        contained_content: list[
            HtmlTemplate | ClcRichtextInlineNodeTemplate] = []
        for content_segment in node.content:
            if isinstance(content_segment, str):
                contained_content.append(
                    PlaintextTemplate(text=content_segment))

            elif isinstance(content_segment, RichtextInlineNode):
                contained_content.append(
                    ClcRichtextInlineNodeTemplate.from_ast_node(
                        content_segment, doc_coll))

            else:
                raise TypeError(
                    'Invalid child of inline richtext node!', content_segment)

        plugin_attrs, plugin_widgets = _apply_plugins(
            doc_coll, RichtextInlineNode, node)
        info = node.info
        if info is None:
            return cls(
                metadata=[],
                body=contained_content,
                spectype_attrs=[],
                plugin_attrs=plugin_attrs,
                plugin_widgets=plugin_widgets)

        else:
            return cls(
                metadata=ClcMetadataTemplate.from_ast_node(
                    node.info, doc_coll) if node.info is not None else [],
                body=contained_content,
                tag_wrappers=_derive_inlinenode_tag_wrappers(
                    cast(InlineNodeInfo, info), doc_coll=doc_coll),
                spectype_attrs=_transform_spec_metadatas_inline(
                    info,
                    doc_coll=doc_coll),
                plugin_attrs=plugin_attrs,
                plugin_widgets=plugin_widgets)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        '<clc-p role="paragraph">{slot.body}</clc-p>',
        loader=INLINE_TEMPLATE_LOADER))
class ClcParagraphTemplate:
    """As the name suggests, used for cleancopy paragraphs.

    Notes:
    ++  because we have <ul>/<ol> next to <p> within the same
        cleancopy paragraph, and because both list tags in HTML are
        invalid inside paragraphs, we need to use a custom tag
    ++  this will inherit from HtmlGenericElement, which has the same
        API surface as a normal div
    ++  this can be styled as desired
    """
    body: Slot[
        ClcRichtextInlineNodeTemplate
        | ClcAnnotationTemplate
        | ClcListTemplate]

    @classmethod
    def from_ast_node(
            cls,
            node: Paragraph,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        body = []
        for nested in node.content:
            if isinstance(nested, RichtextInlineNode):
                body.append(
                    ClcRichtextInlineNodeTemplate.from_ast_node(
                        nested, doc_coll))

            elif isinstance(nested, List_):
                body.append(
                    ClcListTemplate.from_ast_node(nested, doc_coll))

            elif isinstance(nested, Annotation):
                body.append(
                    ClcAnnotationTemplate.from_ast_node(nested, doc_coll))

            else:
                raise TypeError('Invalid child of paragraph!', nested)

        return cls(body=body)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <{content.tag}>
                {slot.items}
            </{content.tag}>'''),
        loader=INLINE_TEMPLATE_LOADER))
class ClcListTemplate:
    """Annotations get converted to comments.
    """
    tag: Content[str]
    items: Slot[ClcListItemTemplate]

    @classmethod
    def from_ast_node(
            cls,
            node: List_,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        if node.type_ is ListType.ORDERED:
            tag = 'ol'
        else:
            tag = 'ul'

        items: list[ClcListItemTemplate] = []
        for nested in node.content:
            items.append(ClcListItemTemplate.from_ast_node(nested, doc_coll))

        return cls(
            tag=tag,
            items=items)


def _transform_listitem_index(value: int | None) -> str:
    if value is None:
        return ''
    else:
        return f' value="{value}"'


@ext_dataclass(
    html,
    TemplateResourceConfig(
        '<li{content.index}>{slot.body}</li>',
        loader=INLINE_TEMPLATE_LOADER))
class ClcListItemTemplate:
    """Annotations get converted to comments.
    """
    index: Content[int | None] = ext_field(FieldConfig(
        transformer=_transform_listitem_index))
    body: Slot[ClcParagraphTemplate]  # type: ignore

    @classmethod
    def from_ast_node(
            cls,
            node: ListItem,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        body: list[ClcParagraphTemplate] = [
            ClcParagraphTemplate.from_ast_node(paragraph, doc_coll)
            for paragraph in node.content]

        return cls(
            index=node.index,
            body=body)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        '<!--{var.text}-->',
        loader=INLINE_TEMPLATE_LOADER))
class ClcAnnotationTemplate:
    """Annotations get converted to comments.
    """
    text: Var[str]

    @classmethod
    def from_ast_node(
            cls,
            node: Annotation,
            doc_coll: HtmlDocumentCollection
            ) -> Self:
        return cls(text=node.content)


def wrap_node_start(
        wrappers: Sequence[NodeContentTagWrapper]
        ) -> list[TemplateClassInstance | InjectedValue | str]:
    """Use this to inject any required start tags at the beginning of
    node content.

    TODO: replace this (and wrap_node_end) with a property-based slot.
    """
    retval: list[TemplateClassInstance | InjectedValue | str] = []
    for wrapper in wrappers:
        retval.append(InjectedValue('<', use_variable_escaper=False))
        retval.append(wrapper.tag)

        for attr in wrapper.attrs:
            retval.append(' ')
            retval.append(attr)

        retval.append(InjectedValue('>', use_variable_escaper=False))

    return retval


def wrap_node_end(
        wrappers: Sequence[NodeContentTagWrapper]
        ) -> list[TemplateClassInstance | InjectedValue | str]:
    """Use this to inject any required end tags at the end of node
    content.
    """
    retval: list[TemplateClassInstance | InjectedValue | str] = []
    for wrapper in reversed(wrappers):
        retval.append(InjectedValue('</', use_variable_escaper=False))
        retval.append(wrapper.tag)
        retval.append(InjectedValue('>', use_variable_escaper=False))

    return retval


@dataclass(slots=True, frozen=True)
class NodeContentTagWrapper:
    """Node body tag wrappers are used to wrap the content of a
    particular node -- ie, its header and body -- with a different
    html tag.
    """
    tag: str
    attrs: Sequence[HtmlAttr]


def formatting_factory_inline(
        spectype: InlineFormatting,
        ) -> NodeContentTagWrapper:
    """Converts a formatting spectype into a ``NodeContentTagWrapper``.
    """
    if spectype is InlineFormatting.PRE:
        tag = 'code'
        attrs = [HtmlAttr(key='class', value=INLINE_PRE_CLASSNAME)]

    elif spectype is InlineFormatting.UNDERLINE:
        tag = UNDERLINE_TAGNAME
        attrs = []

    elif spectype is InlineFormatting.STRONG:
        tag = 'strong'
        attrs = []

    elif spectype is InlineFormatting.EMPHASIS:
        tag = 'em'
        attrs = []

    elif spectype is InlineFormatting.STRIKE:
        tag = 's'
        attrs = []

    elif spectype is InlineFormatting.QUOTE:
        tag = 'q'
        attrs = []

    else:
        raise TypeError(
            'Invalid spectype for inline formatting!', spectype)

    return NodeContentTagWrapper(tag, attrs)


def formatting_factory_block(
        spectype: BlockFormatting,
        ) -> NodeContentTagWrapper:
    """Converts a formatting spectype into a ``NodeContentTagWrapper``.
    """
    if spectype is BlockFormatting.QUOTE:
        tag = 'blockquote'
        attrs = []

    else:
        raise TypeError(
            'Invalid spectype for inline formatting!', spectype)

    return NodeContentTagWrapper(tag, attrs)


def _derive_inlinenode_tag_wrappers(
        info: InlineNodeInfo,
        *,
        doc_coll: HtmlDocumentCollection
        ) -> list[NodeContentTagWrapper]:
    """Checks for any applicable spectype metadata defined on the
    node info, and converts it into node content tag wrappers.
    """
    wrappers: list[NodeContentTagWrapper] = []

    if info.semantic_modifiers is not None:
        wrappers.append(
            NodeContentTagWrapper(info.semantic_modifiers.value, []))

    if info.target is not None:
        if isinstance(info.target, StrDataType):
            href = html_escape(info.target.value, quote=True)
        else:
            href = doc_coll.target_resolver(info.target)

        wrappers.append(
            NodeContentTagWrapper('a', [HtmlAttr('href', href)]))

    if info.formatting is not None:
        wrappers.append(formatting_factory_inline(info.formatting))

    return wrappers


def _derive_blocknode_tag_wrappers(
        info: BlockNodeInfo,
        *,
        doc_coll: HtmlDocumentCollection
        ) -> list[NodeContentTagWrapper]:
    """Checks for any applicable spectype metadata defined on the
    node info, and converts it into node content tag wrappers.
    """
    wrappers: list[NodeContentTagWrapper] = []

    if info.semantic_modifiers is not None:
        wrappers.append(
            NodeContentTagWrapper(info.semantic_modifiers.value, []))

    if info.target is not None:
        if isinstance(info.target, StrDataType):
            href = html_escape(info.target.value, quote=True)
        else:
            href = doc_coll.target_resolver(info.target)

        wrappers.append(
            NodeContentTagWrapper('a', [HtmlAttr('href', href)]))

    if info.formatting is not None:
        wrappers.append(formatting_factory_block(info.formatting))

    return wrappers


def _apply_plugins[T: ASTNode](
        doc_coll: HtmlDocumentCollection,
        node_type: type[T],
        node: T
        ) -> tuple[list[HtmlAttr], list[TemplateClassInstance]]:
    plugins = doc_coll.plugin_manager.get_clc_plugins(node_type)
    plugin_attrs: list[HtmlAttr] = []
    plugin_widgets: list[TemplateClassInstance] = []

    for plugin in plugins:
        injection = plugin(node)
        if injection is not None:
            if injection.attrs is not None:
                plugin_attrs.extend(injection.attrs)
            if injection.widgets is not None:
                plugin_widgets.extend(injection.widgets)

    return plugin_attrs, plugin_widgets
