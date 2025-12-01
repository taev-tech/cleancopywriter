from __future__ import annotations

import typing
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

from cleancopywriter.html.generic_templates import HtmlAttr
from cleancopywriter.html.generic_templates import HtmlGenericElement
from cleancopywriter.html.generic_templates import HtmlTemplate
from cleancopywriter.html.generic_templates import PlaintextTemplate
from cleancopywriter.html.generic_templates import heading_factory
from cleancopywriter.html.generic_templates import link_factory

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


def _transform_spec_metadatas_block(value: BlockNodeInfo | None) -> str:  # noqa: C901
    if value is None:
        return ''

    spec_metadatas: dict[str, object] = {}
    for enum_member in BlockMetadataMagic:
        fieldname = enum_member.name

        # Skip this because it's only relevant for processing the AST
        if fieldname == 'is_doc_metadata':
            continue

        field_value = getattr(value, fieldname)
        if field_value is not None:
            # These are both enums that need special handling
            if fieldname == 'formatting':
                coerced_field_value = field_value.name.lower()
            elif fieldname == 'fallback':
                coerced_field_value = field_value.name.lower()
            elif isinstance(
                field_value,
                MentionDataType
                | TagDataType
                | VariableDataType
                | ReferenceDataType
            ):
                raise NotImplementedError(
                    'Non-string link targets not yet supported for spectype '
                    + 'metadata', fieldname)
            else:
                coerced_field_value = html_escape(
                    field_value.value, quote=True)

            spec_metadatas[fieldname] = coerced_field_value

    # Short-circuit so that we don't get an extra space for an empty list
    if not spec_metadatas:
        return ''

    # First empty string here is so that we get an extra space at the beginning
    # of the list
    to_join: list[str] = ['']
    for fieldname in sorted(spec_metadatas):
        if fieldname == 'embed':
            coerced_fieldname = 'embedding'
        else:
            coerced_fieldname = fieldname.replace('_', '-')

        coerced_value = spec_metadatas[fieldname]
        to_join.append(f'{coerced_fieldname}="{coerced_value}"')

    return ' '.join(to_join)


def _transform_spec_metadatas_inline(value: InlineNodeInfo | None) -> str:
    if value is None:
        return ''

    spec_metadatas: dict[str, object] = {}
    for enum_member in InlineMetadataMagic:
        fieldname = enum_member.name

        # Skip these because they're handled by the actual processing code
        if fieldname in {'target', 'formatting', 'sugared'}:
            continue

        field_value = getattr(value, fieldname)
        if field_value is not None:
            if isinstance(
                field_value,
                MentionDataType
                | TagDataType
                | VariableDataType
                | ReferenceDataType
            ):
                raise NotImplementedError(
                    'Non-string link targets not yet supported for spectype '
                    + 'metadata', fieldname)
            else:
                coerced_field_value = html_escape(
                    field_value.value, quote=True)

            spec_metadatas[fieldname] = coerced_field_value

    # Short-circuit so that we don't get an extra space for an empty list
    if not spec_metadatas:
        return ''

    # First empty string here is so that we get an extra space at the beginning
    # of the list
    to_join: list[str] = ['']
    for fieldname in sorted(spec_metadatas):
        coerced_fieldname = fieldname.replace('_', '-')
        coerced_value = spec_metadatas[fieldname]
        to_join.append(f'{coerced_fieldname}="{coerced_value}"')

    return ' '.join(to_join)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        '<clc-metadata type="{content.type_}" key="{var.key}" '
        + 'value="{var.value}"></clc-metadata>',
        loader=INLINE_TEMPLATE_LOADER))
class ClcMetadataTemplate:
    """This template is used for individual metadata key/value pairs.
    """
    type_: Content[str]
    key: Var[object]
    value: Var[object]

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
                retval.append(cls(
                    type_=DATATYPE_NAMES[type(datatyped_value)],
                    key=key,
                    value=html_escape(datatyped_value.value, quote=True)))

        return retval


def _transform_block_role(value: bool) -> str:
    if value:
        return ' role="article"'
    else:
        return ''


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <clc-block type="richtext"{content.nodeinfo}{
                    slot.plugin_attrs: __prefix__=' '}>
                <clc-header>
                    {slot.title}
                    <clc-metadatas>
                        {slot.metadata}
                    </clc-metadatas>
                </clc-header>
                {slot.body}
                <clc-widgets>{slot.plugin_widgets}</clc-widgets>
            </clc-block>'''),
        loader=INLINE_TEMPLATE_LOADER))
class ClcRichtextBlocknodeTemplate:
    """This template is used for richtext block nodes. Note that it
    differs (only slightly) from the template used for embedding block
    nodes.
    """
    title: Slot[HtmlGenericElement]
    metadata: Slot[ClcMetadataTemplate]
    body: Slot[
        ClcParagraphTemplate
        | ClcEmbeddingBlocknodeTemplate
        | ClcRichtextBlocknodeTemplate]

    plugin_attrs: Slot[HtmlAttr]
    plugin_widgets: DynamicClassSlot

    nodeinfo: Content[BlockNodeInfo | None] = ext_field(FieldConfig(
        transformer=_transform_spec_metadatas_block))
    role_if_root: Content[bool] = template_field(FieldConfig(
        transformer=_transform_block_role))

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
        return cls(
            title=title,
            metadata=ClcMetadataTemplate.from_ast_node(
                node.info, doc_coll) if node.info is not None else [],
            role_if_root=node.depth <= 0,
            body=templatified_content,
            nodeinfo=node.info,
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
            <clc-block type="embedding"{content.nodeinfo}{
                    slot.plugin_attrs: __prefix__=' '}>
                <clc-header>
                    {slot.title}
                    <clc-metadatas>
                        {slot.metadata}
                    </clc-metadatas>
                </clc-header>
                {slot.embedding_content}
                <clc-widgets>{slot.plugin_widgets}</clc-widgets>
            </clc-block>'''),
        loader=INLINE_TEMPLATE_LOADER))
class ClcEmbeddingBlocknodeTemplate:
    """This template is used to contain embedding block
    nodes. Note that it differs (only slightly) from the template used
    for richtext block nodes.
    """
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

    nodeinfo: Content[BlockNodeInfo | None] = ext_field(FieldConfig(
        transformer=_transform_spec_metadatas_block))

    @classmethod
    def from_ast_node(
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

        return cls(
            title=title,
            metadata=ClcMetadataTemplate.from_ast_node(node.info, doc_coll),
            embedding_content=embedding_content,
            nodeinfo=node.info,
            plugin_attrs=plugin_attrs,
            plugin_widgets=plugin_widgets)


@ext_dataclass(
    html,
    TemplateResourceConfig(
        dedent('''\
            <clc-context{content.nodeinfo}{slot.plugin_attrs: __prefix__=' '}>
                <clc-header>
                    <clc-metadatas>
                        {slot.metadata}
                    </clc-metadatas>
                </clc-header>
                {slot.body}
                <clc-widgets>{slot.plugin_widgets}</clc-widgets>
            </clc-context>'''),
        loader=INLINE_TEMPLATE_LOADER))
class ClcRichtextInlineNodeTemplate:
    """This is used as the outermost wrapper for inline richtext nodes.
    Note that all text is wrapped in one of these -- including text
    within titles -- and therefore a ``<p>`` tag cannot be used (because
    they aren't valid within ``<h#>`` tags).
    """
    metadata: Slot[ClcMetadataTemplate]
    body: Slot[HtmlTemplate | ClcRichtextInlineNodeTemplate]  # type: ignore

    plugin_attrs: Slot[HtmlAttr]
    plugin_widgets: DynamicClassSlot

    nodeinfo: Content[InlineNodeInfo | None] = ext_field(FieldConfig(
        transformer=_transform_spec_metadatas_inline))

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
                nodeinfo=None,
                plugin_attrs=plugin_attrs,
                plugin_widgets=plugin_widgets)

        else:
            return cls(
                metadata=ClcMetadataTemplate.from_ast_node(
                    node.info, doc_coll) if node.info is not None else [],
                body=_wrap_in_richtext_context(
                    contained_content,
                    cast(InlineNodeInfo, info),
                    doc_coll=doc_coll),
                nodeinfo=info,
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


def formatting_factory(
        spectype: InlineFormatting,
        body: list[HtmlTemplate | ClcRichtextInlineNodeTemplate]
        ) -> HtmlGenericElement:
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

    return HtmlGenericElement(
        tag=tag,
        attrs=attrs,
        body=body)


def _wrap_in_richtext_context(
        contained_content: list[HtmlTemplate | ClcRichtextInlineNodeTemplate],
        info: InlineNodeInfo,
        *,
        doc_coll: HtmlDocumentCollection
        ) -> list[HtmlTemplate | ClcRichtextInlineNodeTemplate]:
    if info.formatting is not None:
        contained_content = [formatting_factory(
            info.formatting,
            contained_content)]

    if info.target is None:
        return contained_content
    else:
        if isinstance(info.target, StrDataType):
            href = info.target.value
        else:
            href = doc_coll.target_resolver(info.target)

        return [link_factory(
            href=href,
            body=contained_content)]  # type: ignore


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
