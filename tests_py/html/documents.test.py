from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cleancopy.ast import ASTNode
from cleancopy.ast import Document as ClcDocument
from cleancopy.ast import RichtextBlockNode

from cleancopywriter.html.documents import apply_transformers


class TestTreeTransformation:

    def test_no_transformers(self):
        """A tree transformation that has no transformers must simply
        return the original document back.
        """
        document = ClcDocument(
            title=None,
            info=None,
            root=RichtextBlockNode(
                title=None,
                info=None,
                depth=0,
                content=[]))

        result = apply_transformers(document, [], None)

        assert result is document

    def test_node_removal(self):
        """A transformer that removes nodes past a certain depth must
        remove the targeted nodes from the document tree, but other
        nodes must remain unchanged.
        """
        document = ClcDocument(
            title=None,
            info=None,
            root=RichtextBlockNode(
                title=None,
                info=None,
                depth=0,
                content=[
                    RichtextBlockNode(
                        title=None,
                        info=None,
                        depth=1,
                        content=[])]))

        def _strip_nested_nodes(
                node: ASTNode | None,
                *,
                context: Any | None = None
                ) -> ASTNode | None:
            if getattr(node, 'depth', 0) > 0:
                return None

            else:
                return node

        result = apply_transformers(document, [_strip_nested_nodes], None)

        assert len(result.root.content) == 0

    def test_noop_is_equal(self):
        """A noop transformer must return a result that is equal to
        the original tree.
        """
        document = ClcDocument(
            title=None,
            info=None,
            root=RichtextBlockNode(
                title=None,
                info=None,
                depth=0,
                content=[
                    RichtextBlockNode(
                        title=None,
                        info=None,
                        depth=1,
                        content=[])]))

        def _noop(
                node: ASTNode | None,
                *,
                context: Any | None = None
                ) -> ASTNode | None:
            return node

        result = apply_transformers(document, [_noop], None)

        assert result == document

    def test_context_mutation(self):
        """A transformer that requires a context must be passed it
        during transformation, and any mutations to that context during
        transformation must persist past the end of the transformation.
        """
        @dataclass(slots=True)
        class TransformerState:
            sentinel: int = 0

        document = ClcDocument(
            title=None,
            info=None,
            root=RichtextBlockNode(
                title=None,
                info=None,
                depth=0,
                content=[
                    RichtextBlockNode(
                        title=None,
                        info=None,
                        depth=1,
                        content=[])]))

        def _noop(
                node: ASTNode | None,
                *,
                context: TransformerState | None = None
                ) -> ASTNode | None:
            assert isinstance(context, TransformerState)
            context.sentinel += 1
            return node

        state_before = TransformerState()
        result = apply_transformers(document, [_noop], state_before)

        assert result == document
        # Note that this won't be 1 because it'll be called on each node
        assert state_before.sentinel == 3
