from __future__ import annotations

import asyncio


def node_hits(device_id: str, payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("error") or payload.get("_diagnostic"):
        raise ValueError("Node search did not return a successful search response")
    if not any(isinstance(payload.get(section), list) for section in ("fused", "lexical", "gitnexus", "exact_matches")):
        raise ValueError("Node returned an unsupported search response")
    hits, seen = [], set()
    for section in ("exact_matches", "fused", "lexical", "gitnexus"):
        for rank, original in enumerate(payload.get(section, []), 1):
            if not isinstance(original, dict):
                continue
            item = dict(original)
            path = item.get("filePath") or item.get("file") or item.get("path")
            key = (item.get("repoId"), path, item.get("startLine", item.get("line")), item.get("endLine"))
            if key in seen:
                continue
            seen.add(key)
            item.update(deviceId=device_id, repoId=item.get("repoId"), repoName=item.get("repoName"),
                        filePath=path, source=item.get("source") or section,
                        nodeRank=rank, nodeSection=section)
            hits.append(item)
    return hits


async def search_devices(connections: dict, query: str, device_ids: list[str] | None = None,
                         repo: dict[str, str] | None = None, limit: int = 8,
                         timeout: float = 60, concurrency: int = 4) -> dict:
    if not query.strip():
        raise ValueError("query must not be empty")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    selected = sorted(connections) if device_ids is None else list(dict.fromkeys(device_ids))
    unknown = set(selected) - set(connections)
    if unknown:
        raise ValueError(f"Unknown or disabled devices: {', '.join(sorted(unknown))}")
    repo_id = ""
    if repo is not None:
        if set(repo) != {"deviceId", "repoId"} or not all(isinstance(v, str) and v for v in repo.values()):
            raise ValueError("repo must contain deviceId and repoId")
        if repo["deviceId"] not in selected:
            raise ValueError("repo.deviceId is not among the selected enabled devices")
        selected, repo_id = [repo["deviceId"]], repo["repoId"]
    slots = asyncio.Semaphore(concurrency)

    async def search_one(device_id):
        try:
            async with slots:
                async with asyncio.timeout(timeout):
                    payload = await connections[device_id].call(
                        "hybrid_code_search", {"query": query, "repo": repo_id, "limit": limit},
                    )
            return device_id, node_hits(device_id, payload), payload.get("status", {}), None
        except Exception as exc:
            return device_id, [], {}, str(exc) or type(exc).__name__

    responses = await asyncio.gather(*(search_one(device) for device in selected))
    # Scores from independent indexes are not calibrated; deterministic round
    # robin retains each node's ordering and the original score fields.
    merged = []
    for rank in range(max((len(r[1]) for r in responses), default=0)):
        for _, hits, _, _ in responses:
            if rank < len(hits):
                merged.append(hits[rank])
    errors = {device: error for device, _, _, error in responses if error}
    return {
        "query": query, "results": merged[:limit], "partial": bool(errors),
        "errors": errors, "devicesQueried": selected,
        "nodeStatus": {device: status for device, _, status, error in responses if not error},
        "mergeStrategy": "round_robin_node_rank", "limit": limit,
    }
