#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gh_skill_index.py —— GitHub 技能源（SKILL.md）索引、检索与安装

无需 token 即可工作（仓库搜索 10 次/分、核心 API 60 次/时）；
设置环境变量 GITHUB_TOKEN 或 GH_TOKEN 可升到 5000 次/时。

用法：
  python gh_skill_index.py scan                         # 扫描种子仓库，建立/刷新索引
  python gh_skill_index.py scan --discover "claude skills" --max-new 5
  python gh_skill_index.py search "写作 去AI味"          # 检索（自动扩展中文意图词）
  python gh_skill_index.py search "ppt" --json
  python gh_skill_index.py install --repo obra/superpowers --path skills/brainstorming --as brainstorming
  python gh_skill_index.py stats
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
CACHE = Path(
    os.environ.get("GH_SKILL_CACHE")
    or (Path.home() / ".workbuddy" / "cache" / "gh-skill-index.json")
)
TTL = 7 * 24 * 3600

SEED_REPOS = [
    "anthropics/skills",
    "obra/superpowers",
    "ComposioHQ/awesome-claude-skills",
    "alirezarezvani/claude-skills",
    "mattpocock/skills",
    "addyosmani/agent-skills",
    "Jeffallan/claude-skills",
    "zLanqing/codex-claude-academic-skills",
]

# 噪音路径惩罚：Composio 那类仓库里大量 xxx-automation 是 API 连接器壳，不是可复用方法论技能
PATH_PENALTY = [
    ("-automation", -6),
    ("composio-skills/", -4),
    ("_automation", -6),
    ("-mcp", -3),
]

# 中文意图 → 英文路径/描述检索词（路径多为英文，必须先扩展）
LEXICON = {
    "写作": ["writing", "write", "writer", "draft", "prose"],
    "文风": ["style", "tone", "voice"],
    "腔": ["tone", "voice", "style"],
    "去ai味": ["humaniz", "ai-tone", "natural", "de-ai"],
    "人味": ["humaniz", "natural"],
    "报告": ["report"],
    "公文": ["official", "document", "memo"],
    "表格": ["excel", "xlsx", "sheet", "spreadsheet", "csv"],
    "数据": ["data", "dataset"],
    "分析": ["analy", "insight"],
    "图表": ["chart", "plot", "visual", "graph"],
    "可视化": ["visual", "chart", "plot"],
    "演示": ["slide", "ppt", "presentation", "deck"],
    "幻灯": ["slide", "ppt", "presentation"],
    "图片": ["image", "img", "photo", "picture"],
    "视频": ["video", "clip"],
    "音频": ["audio", "voice", "sound"],
    "翻译": ["translat"],
    "搜索": ["search", "crawl", "scrap", "retriev"],
    "爬虫": ["crawl", "scrap"],
    "代码": ["code", "dev", "program", "coding"],
    "测试": ["test"],
    "审查": ["review", "audit"],
    "文档": ["doc", "document"],
    "笔记": ["note", "memo"],
    "知识": ["knowledge", "wiki"],
    "设计": ["design", "ui", "ux"],
    "排版": ["typeset", "layout", "typography"],
    "公众号": ["wechat", "weixin", "gzh"],
    "营销": ["market", "seo", "growth"],
    "简历": ["resume", "cv"],
    "编排": ["compos", "orchestr", "workflow", "meta-skill"],
    "技能": ["skill"],
    "提示词": ["prompt"],
    "总结": ["summar", "digest"],
    "调研": ["research", "surve"],
    "学习": ["learn", "study", "tutor"],
}

TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
UA = "gh-skill-index/1.0 (skill-workflow-composer-plus)"


# ---------------------------------------------------------------- 基础设施


def _headers(accept="application/vnd.github+json"):
    h = {"Accept": accept, "User-Agent": UA}
    if TOKEN:
        h["Authorization"] = "Bearer " + TOKEN
    return h


def api_get(path, quiet=False):
    """调用 GitHub REST API，返回 (data, headers)。失败返回 (None, error_str)。"""
    url = path if path.startswith("http") else API + path
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as f:
            return json.load(f), dict(f.headers)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if not quiet:
            print(f"  [warn] {e.code} {url} {body}", file=sys.stderr)
        return None, f"HTTP {e.code}"
    except Exception as e:  # 网络错误
        if not quiet:
            print(f"  [warn] {e} {url}", file=sys.stderr)
        return None, str(e)


def raw_get(repo, branch, path, limit=1_500_000):
    url = f"{RAW}/{repo}/{branch}/{urllib.parse.quote(path)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as f:
            data = f.read(limit)
        return data.decode("utf-8", "replace")
    except Exception:
        return None


def load_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": 1, "updated_at": 0, "repos": {}, "descriptions": {}}


def save_cache(c):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    c["updated_at"] = int(time.time())
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(CACHE)


def parse_frontmatter(text):
    """宽容解析 SKILL.md 的 YAML 头，返回 {name, description, triggers}。"""
    out = {"name": "", "description": "", "triggers": ""}
    if not text:
        return out
    m = re.match(r"^\ufeff?---\s*\n(.*?)\n---", text, re.S)
    block = m.group(1) if m else text[:1500]
    for key, field in (
        ("name", "name"),
        ("display_name", "name"),
        ("description_zh", "description"),
        ("description", "description"),
    ):
        mm = re.search(rf"^{key}\s*:\s*(.+?)\s*$", block, re.M)
        if mm and not out[field]:
            v = mm.group(1).strip().strip("'\"")
            out[field] = v
    mm = re.search(r"^(?:triggers|tags|keywords)\s*:\s*(.+?)\s*$", block, re.M)
    if mm:
        out["triggers"] = mm.group(1).strip().strip("'\"[]")
    return out


# ---------------------------------------------------------------- 索引


def repo_meta(repo):
    d, err = api_get(f"/repos/{repo}", quiet=True)
    if not d:
        return None
    return {
        "stars": d.get("stargazers_count", 0),
        "branch": d.get("default_branch", "main"),
        "desc": (d.get("description") or "")[:200],
    }


def scan_repo(cache, repo, force=False, verbose=True):
    """把一个仓库里所有 SKILL.md 路径写进索引（1~2 次 API 调用）。"""
    old = cache["repos"].get(repo)
    if old and not force and time.time() - old.get("scanned_at", 0) < TTL:
        if verbose:
            print(f"  跳过（缓存新鲜）{repo}  {len(old['paths'])} 个技能")
        return old

    meta = repo_meta(repo)
    if not meta:
        if verbose:
            print(f"  跳过（取不到仓库信息）{repo}")
        return None
    br = meta["branch"]
    tree, err = api_get(f"/repos/{repo}/git/trees/{br}?recursive=1")
    if not tree:
        if verbose:
            print(f"  跳过（取不到文件树 {err}）{repo}")
        return None
    paths = [
        x["path"]
        for x in tree.get("tree", [])
        if x.get("type") == "blob" and x["path"].endswith("SKILL.md")
    ]
    entry = {
        "stars": meta["stars"],
        "branch": br,
        "desc": meta["desc"],
        "paths": paths,
        "truncated": bool(tree.get("truncated")),
        "scanned_at": int(time.time()),
    }
    cache["repos"][repo] = entry
    if verbose:
        flag = "（树被截断，结果不完整）" if entry["truncated"] else ""
        print(f"  扫描 {repo} ★{meta['stars']}  →  {len(paths)} 个 SKILL.md {flag}")
    return entry


def discover_repos(query, max_new=5, verbose=True):
    """用仓库搜索发现新技能仓库（按 star 排序，取前若干个）。"""
    q = urllib.parse.quote(f"{query} in:name,description,readme")
    d, err = api_get(f"/search/repositories?q={q}&sort=stars&order=desc&per_page=20")
    if not d:
        return []
    picked, seen = [], {r.lower() for r in SEED_REPOS}
    for it in d.get("items", []):
        full = it["full_name"]
        if full.lower() in seen:
            continue
        if it.get("stargazers_count", 0) < 50:
            continue
        picked.append(full)
        if len(picked) >= max_new:
            break
    if verbose and picked:
        print("  发现候选仓库：" + ", ".join(picked))
    return picked


# ---------------------------------------------------------------- 检索


def expand(query):
    q = query.lower()
    toks = set(w for w in re.findall(r"[a-z0-9][a-z0-9\-]{1,}", q) if len(w) >= 3)
    for zh, ens in LEXICON.items():
        if zh in q:
            toks.update(ens)
    return toks


def cjk_bigrams(text):
    return {text[i : i + 2] for i in range(len(text) - 1) if re.match(r"[\u4e00-\u9fff]{2}", text[i : i + 2])}


def score_path(path, toks):
    """词级命中 > 叶子目录子串 > 全路径子串；再扣噪音惩罚。"""
    p = path.lower()
    parts = p.split("/")
    leaf = parts[-2] if len(parts) >= 2 else p
    segs = set(re.split(r"[/_.\-]", leaf))
    s = 0
    for t in toks:
        if t in segs:
            s += 5
        elif t in leaf:
            s += 3
        elif t in p:
            s += 1
    for sub, pen in PATH_PENALTY:
        if sub in p:
            s += pen
    return s


def enrich(cache, repo, branch, path, use_cache=True):
    key = f"{repo}::{path}"
    if use_cache and key in cache["descriptions"]:
        return cache["descriptions"][key]
    text = raw_get(repo, branch, path)
    fm = parse_frontmatter(text)
    fm["head"] = (text or "")[:0]
    cache["descriptions"][key] = fm
    return fm


def cmd_search(args):
    cache = load_cache()
    if not cache["repos"]:
        print("索引为空，先跑：python gh_skill_index.py scan")
        return 1
    toks = expand(args.query)
    if args.keywords:
        toks.update(k.strip().lower() for k in args.keywords.split(",") if k.strip())
    qbigrams = cjk_bigrams(args.query)

    cands = []
    for repo, meta in cache["repos"].items():
        for p in meta["paths"]:
            sc = score_path(p, toks)
            cands.append((sc, repo, meta["branch"], p, meta["stars"]))
    cands.sort(key=lambda x: (-x[0], -x[4]))

    # 路径命中优先；无命中时按 star 取头部做描述层匹配
    shortlist = [c for c in cands if c[0] > 0][: args.limit * 3]
    if len(shortlist) < args.limit:
        extra = [c for c in cands if c[0] == 0][: max(0, args.limit * 3 - len(shortlist))]
        shortlist += extra

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {
            ex.submit(enrich, cache, c[1], c[2], c[3], not args.refresh_desc): c
            for c in shortlist
        }
        rows = []
        for f, c in ((f, futs[f]) for f in futs):
            fm = f.result()
            desc = (fm.get("description") or "").replace("\n", " ")
            boost = 0
            if qbigrams:
                boost = sum(4 for b in qbigrams if b in desc) + sum(
                    2 for b in qbigrams if b in fm.get("name", "")
                )
            rows.append(
                {
                    "repo": c[1],
                    "path": c[3],
                    "name": fm.get("name") or Path(c[3]).parent.name,
                    "description": desc[:220],
                    "stars": c[4],
                    "score": c[0] + boost,
                    "url": f"https://github.com/{c[1]}/blob/{c[2]}/{c[3]}",
                    "raw": f"{RAW}/{c[1]}/{c[2]}/{urllib.parse.quote(c[3])}",
                    "branch": c[2],
                }
            )
    rows.sort(key=lambda r: (-r["score"], -r["stars"]))
    # 同一仓库里同名同描述的技能可能出现在多个路径，去重保留排序靠前（路径更短者先入）
    seen, uniq = set(), []
    for r in rows:
        k = (r["repo"], r["name"], r["description"][:60])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    rows = uniq[: args.limit]
    save_cache(cache)

    if args.json:
        print(json.dumps({"query": args.query, "tokens": sorted(toks), "results": rows},
                         ensure_ascii=False, indent=1))
        return 0

    print(f"查询：{args.query}")
    print(f"扩展检索词：{', '.join(sorted(toks)) or '(无)'}")
    if not rows or rows[0]["score"] <= 0:
        print("⚠ 当前语料没有直接命中的技能，以下按 star 兜底。"
              "可换英文关键词，或跑 `scan --discover \"...\"` 扩充语料后再查。")
    print()
    print("| # | 技能 | 仓库 / 路径 | 一句话能力 | ★ |")
    print("|---|------|------------|-----------|---|")
    for i, r in enumerate(rows, 1):
        d = r["description"] or "(无描述，需读原文)"
        print(f"| {i} | {r['name']} | {r['repo']}<br>`{r['path']}` | {d} | {r['stars']} |")
    print()
    if rows:
        r = rows[0]
        print(f"首选原文：{r['url']}")
        print(f"安装命令：python {Path(__file__).name} install --repo {r['repo']} "
              f"--path {r['path'].rsplit('/', 1)[0]} --as {Path(r['path']).parent.name}")
    return 0


# ---------------------------------------------------------------- 安装


def cmd_install(args):
    cache = load_cache()
    if args.repo not in cache["repos"]:
        scan_repo(cache, args.repo, force=True)
        save_cache(cache)
    meta = cache["repos"].get(args.repo)
    if not meta:
        print(f"仓库不可用：{args.repo}")
        return 1
    prefix = args.path.rstrip("/") + "/"
    files = [p for p in meta["paths"] if p.startswith(prefix)]
    if not files:
        print(f"路径下没有 SKILL.md：{args.path}")
        return 1
    # 同目录下的其它文件（scripts/references 等）需要完整树，这里补齐
    tree, _ = api_get(f"/repos/{args.repo}/git/trees/{meta['branch']}?recursive=1")
    blobs = []
    if tree:
        for x in tree.get("tree", []):
            if x.get("type") == "blob" and x["path"].startswith(prefix) and x.get("size", 0) < 1_500_000:
                blobs.append(x["path"])
    if not blobs:
        blobs = files

    name = args.a or Path(args.path).name
    root = Path(os.environ.get("WB_SKILLS_DIR") or (Path.home() / ".workbuddy" / "skills"))
    dst = root / name
    if dst.exists() and not args.force:
        print(f"目标已存在：{dst}（加 --force 覆盖）")
        return 1

    ok = 0
    for p in blobs:
        rel = p[len(prefix):]
        text = raw_get(args.repo, meta["branch"], p)
        if text is None:
            print(f"  [skip] 取不到 {p}")
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        ok += 1
    print(f"已安装 {ok}/{len(blobs)} 个文件 → {dst}")
    return 0


def cmd_scan(args):
    cache = load_cache()
    repos = list(SEED_REPOS)
    if args.repos:
        repos += [r.strip() for r in args.repos.split(",") if r.strip()]
    if args.discover:
        repos += discover_repos(args.discover, args.max_new)
    print("扫描 GitHub 技能源：")
    for r in dict.fromkeys(repos):
        scan_repo(cache, r, force=args.refresh)
    save_cache(cache)
    total = sum(len(m["paths"]) for m in cache["repos"].values())
    print(f"索引完成：{len(cache['repos'])} 个仓库，{total} 条技能，缓存 {CACHE}")
    return 0


def cmd_stats(args):
    cache = load_cache()
    if not cache["repos"]:
        print("索引为空")
        return 0
    age = int(time.time() - cache.get("updated_at", 0))
    print(f"缓存：{CACHE}")
    print(f"上次刷新：{age // 3600} 小时前 | 描述缓存 {len(cache.get('descriptions', {}))} 条")
    print()
    print("| 仓库 | ★ | 技能数 | 树截断 |")
    print("|------|---|--------|--------|")
    for repo, m in sorted(cache["repos"].items(), key=lambda kv: -kv[1]["stars"]):
        print(f"| {repo} | {m['stars']} | {len(m['paths'])} | {'是' if m.get('truncated') else '否'} |")
    if not TOKEN:
        print()
        print("提示：未设置 GITHUB_TOKEN，核心 API 限 60 次/时；设了可到 5000 次/时。")
    return 0


def main():
    p = argparse.ArgumentParser(description="GitHub 技能源索引与检索")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="扫描仓库、建立索引")
    s.add_argument("--repos", help="额外仓库，逗号分隔，如 a/b,c/d")
    s.add_argument("--refresh", action="store_true", help="忽略 TTL 强制重扫")
    s.add_argument("--discover", help="用仓库搜索发现新仓库，如 'claude skills'")
    s.add_argument("--max-new", type=int, default=5)
    s.set_defaults(func=cmd_scan)

    q = sub.add_parser("search", help="检索技能")
    q.add_argument("query")
    q.add_argument("--keywords", help="补充英文检索词，逗号分隔")
    q.add_argument("--limit", type=int, default=8)
    q.add_argument("--json", action="store_true")
    q.add_argument("--refresh-desc", action="store_true", help="忽略描述缓存重取")
    q.set_defaults(func=cmd_search)

    i = sub.add_parser("install", help="从 GitHub 安装技能到本地 skills 目录")
    i.add_argument("--repo", required=True)
    i.add_argument("--path", required=True, help="技能目录，如 skills/brainstorming")
    i.add_argument("--as", dest="a", help="本地目录名")
    i.add_argument("--force", action="store_true")
    i.set_defaults(func=cmd_install)

    t = sub.add_parser("stats", help="查看索引状态")
    t.set_defaults(func=cmd_stats)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
