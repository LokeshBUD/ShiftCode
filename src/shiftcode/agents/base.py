import ast
from importlib import resources
from typing import TypeVar

from pydantic import BaseModel

from shiftcode.llm.base import LLMProvider
from shiftcode.llm.errors import LLMOutputError
from shiftcode.models.agent_io import SymbolBlock

T = TypeVar("T", bound=BaseModel)

MODULE_SENTINEL = "__module__"


def load_prompt(name: str) -> str:
    """Load a static prompt template from shiftcode/prompts/<name>.md."""
    return resources.files("shiftcode.prompts").joinpath(f"{name}.md").read_text()


class AgentOutputError(Exception):
    """Raised when an agent's structured output couldn't be parsed even after
    the bounded retry. Orchestrator treats this as NEEDS_REVIEW, never a
    silent guess."""


def render_prompt(static_prefix: str, dynamic_suffix: str) -> str:
    """Static instructions first, per-file dynamic content last, so
    OpenAI-compatible providers auto-cache the stable prefix across the
    repair loop's repeated turns."""
    return f"{static_prefix.rstrip()}\n\n{dynamic_suffix}"


def call_structured(
    provider: LLMProvider,
    *,
    prompt: str,
    schema: type[T],
    system: str | None = None,
    temperature: float = 0.0,
    max_retries: int = 1,
) -> T:
    last_error: Exception | None = None
    current_prompt = prompt
    for _ in range(max_retries + 1):
        try:
            return provider.generate_structured(
                current_prompt, schema=schema, system=system, temperature=temperature
            )
        except LLMOutputError as exc:
            last_error = exc
            current_prompt = (
                f"{prompt}\n\n"
                f"Your previous response could not be parsed as valid {schema.__name__} JSON: {exc}\n"
                f"Return ONLY a valid JSON object matching the schema, no extra text."
            )
    raise AgentOutputError(
        f"could not get valid {schema.__name__} from provider after {max_retries + 1} attempt(s): {last_error}"
    )


class SpliceError(Exception):
    """Symbol couldn't be safely spliced (not found, ambiguous, or blocks
    overlap) - caller should fall back to treating the patch as a full-file
    replacement."""


def _find_symbol_node(tree: ast.Module, symbol: str) -> ast.AST | None:
    parts = symbol.split(".")
    scope_nodes = tree.body
    node = None
    for i, part in enumerate(parts):
        node = next(
            (
                n
                for n in scope_nodes
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.name == part
            ),
            None,
        )
        if node is None:
            return None
        if i < len(parts) - 1:
            if not isinstance(node, ast.ClassDef):
                return None
            scope_nodes = node.body
    return node


def _splice_span(source: str, node: ast.AST, new_code: str) -> str:
    lines = source.splitlines(keepends=True)
    start_line, start_col = node.lineno - 1, node.col_offset
    end_line, end_col = node.end_lineno - 1, node.end_col_offset
    before = "".join(lines[:start_line]) + lines[start_line][:start_col]
    after = lines[end_line][end_col:] + "".join(lines[end_line + 1 :])
    return before + new_code.strip("\n") + "\n" + after


def apply_symbol_blocks(original_source: str, blocks: list[SymbolBlock]) -> str:
    """Splice each SymbolBlock into original_source by locating the symbol's span
    via ast (node.lineno/end_lineno/col_offset) and replacing that byte span.
    Falls back to full-file replacement on the __module__ sentinel; raises
    SpliceError (caller should then fall back to full-file) if a symbol can't be
    resolved or blocks overlap."""
    if any(b.symbol == MODULE_SENTINEL for b in blocks):
        if len(blocks) != 1:
            raise SpliceError(f"{MODULE_SENTINEL} sentinel must be the only block in the patch")
        return blocks[0].new_source

    try:
        tree = ast.parse(original_source)
    except SyntaxError as exc:
        raise SpliceError(f"original source doesn't parse: {exc}") from exc

    resolved = []
    for block in blocks:
        node = _find_symbol_node(tree, block.symbol)
        if node is None:
            raise SpliceError(f"symbol {block.symbol!r} not found")
        resolved.append((node, block.new_source))

    resolved.sort(key=lambda item: (item[0].lineno, item[0].col_offset))
    for (node_a, _), (node_b, _) in zip(resolved, resolved[1:]):
        a_end = (node_a.end_lineno, node_a.end_col_offset)
        b_start = (node_b.lineno, node_b.col_offset)
        if a_end > b_start:
            raise SpliceError(f"overlapping symbol spans: {node_a.name!r} and {node_b.name!r}")

    result = original_source
    for node, new_code in reversed(resolved):
        result = _splice_span(result, node, new_code)
    return result
