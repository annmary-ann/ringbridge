"""Cross-field checks that need the whole AgentSpec: graph integrity, tool scoping, compliance."""

from __future__ import annotations

import re
from collections import deque
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ringbridge_core.spec.issues import Issue, Path
from ringbridge_core.spec.models import AgentSpec
from ringbridge_core.spec.tools import BUILTIN_TOOLS, SIDE_EFFECT_TOOLS

# Names a follow-up `when` expression may use besides the agent's own outcome fields.
FOLLOW_UP_VARIABLES = frozenset({"attempt", "direction", "duration_s"})
_KNOWN_TOOLS = ", ".join(sorted(BUILTIN_TOOLS))
_EXPR_KEYWORDS = frozenset({"and", "or", "not", "in", "is", "true", "false", "none"})
_STRING_LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")
_IDENTIFIER = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b")


def check(agent: AgentSpec) -> list[Issue]:
    issues: list[Issue] = []
    body = agent.spec
    graph = body.graph
    root: Path = ("spec",)

    def err(path: Path, msg: str) -> None:
        issues.append(Issue("error", path, msg))

    def warn(path: Path, msg: str) -> None:
        issues.append(Issue("warning", path, msg))

    # ---- disclosures (ADR-0013)
    d = body.disclosures
    if d.unsafe_disable_disclosure:
        warn(
            (*root, "disclosures", "unsafe_disable_disclosure"),
            "disclosure check is disabled; you are responsible for AI and recording disclosure",
        )
    elif not d.greeting.strip():
        err(
            (*root, "disclosures", "greeting"),
            "a disclosure greeting is required (say it is an AI assistant and whether the call is "
            "recorded); set unsafe_disable_disclosure: true to opt out",
        )

    # ---- language (ADR-0014)
    lang = body.language
    locales = {lang.default, *lang.allowed}
    if lang.default in lang.allowed:
        warn((*root, "language", "allowed"), f"{lang.default!r} is the default; no need to list it")
    if lang.detect and not lang.allowed:
        warn((*root, "language", "detect"), "detect is on but no other locales are allowed")
    for loc in body.voice.overrides:
        if loc not in locales:
            err(
                (*root, "voice", "overrides", loc),
                f"override for {loc!r}, which is not the default or an allowed locale",
            )

    # ---- business
    try:
        ZoneInfo(body.business.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        err(
            (*root, "business", "timezone"),
            f"unknown time zone {body.business.timezone!r}; use an IANA name like Asia/Kolkata",
        )

    # ---- graph integrity
    gpath: Path = (*root, "graph")
    if graph.start not in graph.nodes:
        err((*gpath, "start"), f"start node {graph.start!r} is not defined in nodes")

    for nid, node in graph.nodes.items():
        npath: Path = (*gpath, "nodes", nid)
        for i, t in enumerate(node.transitions):
            if t.to not in graph.nodes:
                err((*npath, "transitions", i, "to"), f"transition to unknown node {t.to!r}")
            elif t.to == nid:
                warn((*npath, "transitions", i, "to"), "transition points back to the same node")

        seen: set[str] = set()
        for i, tool in enumerate(node.tools):
            if tool not in BUILTIN_TOOLS:
                err(
                    (*npath, "tools", i),
                    f"unknown tool {tool!r}; built-in tools are: {_KNOWN_TOOLS}",
                )
            if tool in seen:
                warn((*npath, "tools", i), f"tool {tool!r} is listed twice")
            seen.add(tool)

        guarded = {g.confirm_before for g in node.guardrails}
        for i, g in enumerate(node.guardrails):
            if g.confirm_before not in node.tools:
                err(
                    (*npath, "guardrails", i, "confirm_before"),
                    f"confirm_before {g.confirm_before!r} is not in this node's tools",
                )
        for i, tool in enumerate(node.tools):
            if tool in SIDE_EFFECT_TOOLS and tool not in guarded:
                warn(
                    (*npath, "tools", i),
                    f"{tool!r} has side effects; add a guardrail `confirm_before: {tool}`",
                )

        if node.action == "transfer" and "call.transfer" in node.tools:
            warn((*npath, "tools"), "action: transfer already transfers; drop call.transfer")

    if graph.start in graph.nodes:
        reachable = _reachable(agent)
        for nid in graph.nodes:
            if nid not in reachable:
                warn((*gpath, "nodes", nid), f"node {nid!r} cannot be reached from {graph.start!r}")
        if not any(
            "call.end" in graph.nodes[n].tools or graph.nodes[n].action == "transfer"
            for n in reachable
        ):
            warn(gpath, "no reachable node can end the call (call.end) or transfer it")

    # ---- post-call
    fields = set(body.post_call.extract)
    for i, fu in enumerate(body.post_call.follow_ups):
        fpath: Path = (*root, "post_call", "follow_ups", i)
        for name in _identifiers(fu.when):
            if name not in fields and name not in FOLLOW_UP_VARIABLES:
                known = ", ".join(sorted(fields | FOLLOW_UP_VARIABLES)) or "none"
                err((*fpath, "when"), f"unknown name {name!r} in condition; known: {known}")
        if fu.send and fu.send.fallback == fu.send.channel:
            err((*fpath, "send", "fallback"), "fallback channel is the same as the channel")

    return issues


def _reachable(agent: AgentSpec) -> set[str]:
    nodes = agent.spec.graph.nodes
    seen = {agent.spec.graph.start}
    queue = deque(seen)
    while queue:
        for t in nodes[queue.popleft()].transitions:
            if t.to in nodes and t.to not in seen:
                seen.add(t.to)
                queue.append(t.to)
    return seen


def _identifiers(expr: str) -> list[str]:
    stripped = _STRING_LITERAL.sub("''", expr)
    out: list[str] = []
    for m in _IDENTIFIER.finditer(stripped):
        name = m.group(0)
        if name.lower() not in _EXPR_KEYWORDS and not name.isdigit() and name not in out:
            out.append(name)
    return out
