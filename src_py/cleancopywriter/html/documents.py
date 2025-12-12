from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from functools import singledispatch
from typing import Annotated
from typing import Any
from typing import cast
from typing import overload

from cleancopy import Abstractifier
from cleancopy import parse
from cleancopy.ast import Annotation
from cleancopy.ast import ASTNode
from cleancopy.ast import BlockNode
from cleancopy.ast import Document as ClcDocument
from cleancopy.ast import EmbeddingBlockNode
from cleancopy.ast import List_
from cleancopy.ast import ListItem
from cleancopy.ast import Paragraph
from cleancopy.ast import RichtextBlockNode
from cleancopy.ast import RichtextInlineNode
from docnote import Note
from docnote_extract import SummaryTreeNode
from templatey._types import TemplateClassInstance
from templatey.environments import RenderEnvironment
from templatey.prebaked.loaders import InlineStringTemplateLoader

from cleancopywriter._types import ClcTreeTransformer
from cleancopywriter._types import DocumentBase
from cleancopywriter._types import DocumentID
from cleancopywriter._types import LinkTargetResolver
from cleancopywriter.html.plugin_types import PluginManager
from cleancopywriter.html.prebaked.plugins import SimplePluginManager
from cleancopywriter.html.templatifiers.clc import ClcRichtextBlocknodeTemplate
from cleancopywriter.html.templatifiers.clc import wrap_node_end
from cleancopywriter.html.templatifiers.clc import wrap_node_start
from cleancopywriter.html.templatifiers.docnotes import ModuleSummaryTemplate


@dataclass(slots=True)
class HtmlDocument[TI: DocumentID, TS](
        DocumentBase[TI, TS, TemplateClassInstance]):
    """This is used as a base class for all supported html document
    types.
    """


@dataclass(slots=True)
class DocnoteHtmlDocument[TI: DocumentID](HtmlDocument[TI, SummaryTreeNode]):
    """This is used for all documents constructed from a docnote
    extraction.
    """


@dataclass(slots=True)
class ClcHtmlDocument[TI: DocumentID](HtmlDocument[TI, ClcDocument]):
    """This is used for all documents constructed from a cleancopy
    document.
    """


@dataclass(slots=True)
class _ProxyViewDescriptor:
    """This is a bit of a hack. The goal here is to allow dataclasses
    to include generated views into things **as part of their repr**.
    The general strategy is to use a non-init field as a proxy to the
    view_builder attribute.

    Instead of using a [[descriptor-typed
    field](https://docs.python.org/3/library/dataclasses.html#descriptor-typed-fields)]
    -- which cannot be assigned init=False -- we simply set the field
    as normal, allow the dataclass to be processed, **and then**
    overwrite the field with the descriptor.
    """
    view_builder: Callable[[Any], Any]

    def __get__(self, obj: Any | None, objtype: type | None = None):
        if obj is None:
            return '...'
        elif objtype is None:
            return '...'
        else:
            return self.view_builder(obj)


@dataclass(slots=True, kw_only=True)
class HtmlDocumentCollection[T: DocumentID, TC](Mapping[T, HtmlDocument]):
    target_resolver: LinkTargetResolver
    plugin_manager: PluginManager = field(default_factory=SimplePluginManager)
    transformers: Annotated[
            Sequence[ClcTreeTransformer[TC]],
            Note('''Transformers can be used to modify the content of
                cleancopy documents during preprocessing. For example, they
                are responsible for converting simple ``code`` references in
                docnotes to references to their values in the current
                namespace.

                Note that the order of the transformers will match the order
                they are applied in.''')
        ] = field(default_factory=list)

    abstractifier: Abstractifier = field(default_factory=Abstractifier)

    _documents: dict[T, HtmlDocument] = field(default_factory=dict, repr=False)
    # This gets replaced by a _ProxyViewDescriptor!
    documents: tuple[T, ...] = field(init=False)

    def preprocess(
            self,
            clc_text: bytes | str,
            *,
            context: TC | None = None
            ) -> ClcDocument:
        """Applies any cleancopy tree transformers and returns the
        resulting cleancopy document AST.
        """
        if isinstance(clc_text, str):
            clc_text = clc_text.encode('utf-8')

        cst_doc = parse(clc_text)
        ast_doc = self.abstractifier.convert(cst_doc)
        return apply_transformers(ast_doc, self.transformers, context)

    @overload
    def add(self, id_: T, *, docnote_src: SummaryTreeNode) -> None: ...
    @overload
    def add(self, id_: T, *, clc_src: ClcDocument) -> None: ...

    def add(
            self,
            id_: T,
            *,
            docnote_src: SummaryTreeNode | None = None,
            clc_src: ClcDocument | None = None
            ) -> None:
        """Constructs a document from the passed source object and adds
        it to the collection.
        """
        if id_ in self._documents:
            raise ValueError('Duplicate document ID!', id_)

        if (
            docnote_src is not None
            # We're anticipating adding more document types here, hence the
            # all() instead of a simple singular ``is None`` check
            and all(alt_src is None for alt_src in (clc_src,))
        ):
            self._documents[id_] = DocnoteHtmlDocument(
                id_=id_,
                src=docnote_src,
                intermediate_representation=ModuleSummaryTemplate.from_summary(
                    docnote_src.module_summary,
                    self))

        elif (
            clc_src is not None
            # We're anticipating adding more document types here, hence the
            # all() instead of a simple singular ``is None`` check
            and all(alt_src is None for alt_src in (docnote_src,))
        ):
            templatified = ClcRichtextBlocknodeTemplate.from_document(
                clc_src, doc_coll=self)

            self._documents[id_] = ClcHtmlDocument(
                id_=id_,
                src=clc_src,
                intermediate_representation=templatified)

        else:
            raise TypeError(
                'Can only specify one document source when adding to a '
                + 'collection!')

    def __contains__(self, id_: object) -> bool:
        return id_ in self._documents

    def __getitem__(self, id_: T) -> HtmlDocument:
        return self._documents[id_]

    def __iter__(self) -> Iterator[T]:
        return iter(self._documents)

    def __len__(self) -> int:
        return len(self._documents)

    @overload
    def get(self, key: T, /) -> HtmlDocument | None: ...
    @overload
    def get(self, key: T, /, default: HtmlDocument) -> HtmlDocument: ...
    @overload
    def get[TD](self, key: T, /, default: TD) -> TD | HtmlDocument: ...

    def get[TD](
            self,
            key: T,
            /,
            default: TD | HtmlDocument | None = None
            ) ->  TD | HtmlDocument | None:
        return self._documents.get(key, default)

HtmlDocumentCollection.documents = _ProxyViewDescriptor(  # type: ignore
    view_builder=lambda doc_coll: tuple(doc_coll._documents))  # type: ignore


def apply_transformers[T](
        document: ClcDocument,
        transformers: Sequence[ClcTreeTransformer[T]],
        context: T | None
        ) -> ClcDocument:
    """This recursively traverses all of the nodes in the document,
    applying all of the transformers in order.
    """
    # Short-circuit here for performance reasons
    if not transformers:
        return document

    transformed = _apply_transformers(document, transformers, context)
    if not isinstance(transformed, ClcDocument):
        raise TypeError(
            'Invalid transformation result!', document, transformed)

    return transformed


@singledispatch
def _apply_transformers[T](
        node: ASTNode,
        transformers: Sequence[ClcTreeTransformer[T]],
        context: T | None
        ) -> ASTNode:
    """This actually implements the transformations.
    """
    return node


@_apply_transformers.register
def _apply_xform_document[T](
        node: ClcDocument,
        transformers: Sequence[ClcTreeTransformer[T]],
        context: T | None
        ) -> ASTNode:
    if node.title is None:
        new_title = None
    else:
        new_title = _apply_transformers(node.title, transformers, context)
        if not (
            new_title is None
            or isinstance(new_title, RichtextInlineNode)
        ):
            raise TypeError(
                'Invalid transformation result!', node.title, new_title)

    new_root = _apply_transformers(node.root, transformers, context)
    if not isinstance(new_root, RichtextBlockNode):
        raise TypeError(
            'Invalid transformation result!', node.root, new_root)

    new_node = ClcDocument(
        title=new_title,
        info=node.info,
        root=new_root)
    for transformer in transformers:
        new_node = transformer(new_node, context=context)

    return new_node


@_apply_transformers.register
def _apply_xform_richtextblocknode[T](
        node: RichtextBlockNode,
        transformers: Sequence[ClcTreeTransformer[T]],
        context: T | None
        ) -> ASTNode:
    if node.title is None:
        new_title = None
    else:
        new_title = _apply_transformers(node.title, transformers, context)
        if not (
            new_title is None
            or isinstance(new_title, RichtextInlineNode)
        ):
            raise TypeError(
                'Invalid transformation result!', node.title, new_title)

    new_content = [
        _apply_transformers(subnode, transformers, context)
        for subnode in node.content]
    if not all(
        isinstance(new_subnode, Paragraph | BlockNode)
        for new_subnode in new_content
    ):
        raise TypeError(
            'Invalid transformation result!', node.content, new_content)
    new_content = cast(list[Paragraph | BlockNode], new_content)

    new_node = RichtextBlockNode(
        title=new_title,
        info=node.info,
        depth=node.depth,
        content=new_content)
    for transformer in transformers:
        new_node = transformer(new_node, context=context)

    return new_node


@_apply_transformers.register
def _apply_xform_embeddingblocknode[T](
        node: EmbeddingBlockNode,
        transformers: Sequence[ClcTreeTransformer[T]],
        context: T | None
        ) -> ASTNode:
    if node.title is None:
        new_title = None
    else:
        new_title = _apply_transformers(node.title, transformers, context)
        if not (
            new_title is None
            or isinstance(new_title, RichtextInlineNode)
        ):
            raise TypeError(
                'Invalid transformation result!', node.title, new_title)

    new_node = EmbeddingBlockNode(
        title=new_title,
        info=node.info,
        depth=node.depth,
        content=node.content)
    for transformer in transformers:
        new_node = transformer(new_node, context=context)

    return new_node


@_apply_transformers.register
def _apply_xform_paragraph[T](
        node: Paragraph,
        transformers: Sequence[ClcTreeTransformer[T]],
        context: T | None
        ) -> ASTNode:
    new_content = [
        _apply_transformers(subnode, transformers, context)
        for subnode in node.content]
    if not all(
        isinstance(new_subnode, RichtextInlineNode | List_ | Annotation)
        for new_subnode in new_content
    ):
        raise TypeError(
            'Invalid transformation result!', node.content, new_content)
    new_content = cast(
        list[RichtextInlineNode | List_ | Annotation], new_content)

    new_node = Paragraph(
        content=new_content)
    for transformer in transformers:
        new_node = transformer(new_node, context=context)

    return new_node


@_apply_transformers.register
def _apply_xform_list[T](
        node: List_,
        transformers: Sequence[ClcTreeTransformer[T]],
        context: T | None
        ) -> ASTNode:
    new_content = [
        _apply_transformers(subnode, transformers, context)
        for subnode in node.content]
    if not all(
        isinstance(new_subnode, ListItem)
        for new_subnode in new_content
    ):
        raise TypeError(
            'Invalid transformation result!', node.content, new_content)
    new_content = cast(list[ListItem], new_content)

    new_node = List_(
        type_=node.type_,
        content=new_content)
    for transformer in transformers:
        new_node = transformer(new_node, context=context)

    return new_node


@_apply_transformers.register
def _apply_xform_listitem[T](
        node: ListItem,
        transformers: Sequence[ClcTreeTransformer[T]],
        context: T | None
        ) -> ASTNode:
    new_content = [
        _apply_transformers(subnode, transformers, context)
        for subnode in node.content]
    if not all(
        isinstance(new_subnode, Paragraph)
        for new_subnode in new_content
    ):
        raise TypeError(
            'Invalid transformation result!', node.content, new_content)
    new_content = cast(list[Paragraph], new_content)

    new_node = ListItem(
        index=node.index,
        content=new_content)
    for transformer in transformers:
        new_node = transformer(new_node, context=context)

    return new_node


@_apply_transformers.register
def _apply_xform_richtextinlinenode[T](
        node: RichtextInlineNode,
        transformers: Sequence[ClcTreeTransformer[T]],
        context: T | None
        ) -> ASTNode:
    new_content = [
        _apply_transformers(subnode, transformers, context)
        for subnode in node.content]
    if not all(
        isinstance(new_subnode, str | RichtextInlineNode)
        for new_subnode in new_content
    ):
        raise TypeError(
            'Invalid transformation result!', node.content, new_content)
    new_content = cast(list[str | RichtextInlineNode], new_content)

    new_node = RichtextInlineNode(
        info=node.info,
        content=new_content)
    for transformer in transformers:
        new_node = transformer(new_node, context=context)

    return new_node


@_apply_transformers.register
def _apply_xform_annotation[T](
        node: Annotation,
        transformers: Sequence[ClcTreeTransformer[T]],
        context: T | None
        ) -> ASTNode:
    new_node = Annotation(
        content=node.content)
    for transformer in transformers:
        new_node = transformer(new_node, context=context)

    return new_node


def quickrender(
        clc_text: str,
        plugin_manager: PluginManager | None = None
        ) -> str:
    """This is a utility function, mostly intended for manual
    debugging and repl tomfoolery, that renders the passed cleancopy
    text into HTML.
    """
    def target_resolver(*args, **kwargs) -> str:
        return '#'

    if plugin_manager is None:
        doc_coll = HtmlDocumentCollection(target_resolver=target_resolver)
    else:
        doc_coll = HtmlDocumentCollection(
            target_resolver=target_resolver,
            plugin_manager=plugin_manager)

    ast_doc = doc_coll.preprocess(clc_text=clc_text)
    template = ClcRichtextBlocknodeTemplate.from_document(
        ast_doc, doc_coll=doc_coll)
    render_env = RenderEnvironment(
        InlineStringTemplateLoader(),
        [wrap_node_end, wrap_node_start])
    return render_env.render_sync(template)
