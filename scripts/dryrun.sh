#!/usr/bin/env bash
# 干跑清单：不碰浏览器就能验的全部行为。改完 bin/ 里任何东西都要跑一遍。
#
# ⚠️ 它测不到浏览器那一半（开标签页、选档位、注入、发送、判完成）。
#    这份清单全绿不代表能用 —— 还得真跑一次低档位作业。
#
# 用法：./scripts/dryrun.sh
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CGH="$REPO/bin/cgh"
WORK="$(mktemp -d)"
export CGH_LEDGER="$WORK/ledger.jsonl"      # 别污染真实账本
PASS=0; FAIL=0

trap 'rm -rf "$WORK"' EXIT

ok(){   PASS=$((PASS+1)); printf '  ✅ %s\n' "$1"; }
bad(){  FAIL=$((FAIL+1)); printf '  ❌ %s\n     期望 %s，实际 %s\n' "$1" "$2" "$3"; }
# want <说明> <期望子串> <实际输出>
want(){ case "$3" in *"$2"*) ok "$1";; *) bad "$1" "$2" "$(echo "$3" | tr '\n' ' ' | cut -c1-120)";; esac; }

echo "== 1. 语法与可执行 =="
for f in bin/cgh bin/cgh_cdp.py bin/cgh_web.py; do
  if python3 -c "compile(open('$REPO/$f').read(),'$f','exec')" 2>/dev/null; then ok "$f 编译通过"
  else bad "$f 编译" "无语法错" "编译失败"; fi
done
bash -n "$REPO/scripts/install.sh" 2>/dev/null && ok "install.sh 语法通过" || bad "install.sh 语法" "通过" "失败"
want "cgh --help 可用" "usage: cgh" "$("$CGH" --help 2>&1)"

echo "== 2. 作业创建与档位识别 =="
cd "$WORK" && git init -q . && git commit -q --allow-empty -m init

want "别名 pro_extended → pro" '"effort_requested": "pro"' \
     "$("$CGH" new --effort pro_extended --action review --subject "干跑清单用的审查对象" 2>&1)"
JOB=$("$CGH" state 2>&1 | grep -o 'id=[a-z0-9_]*' | cut -d= -f2)
want ".gitignore 已注入" ".chatgpt/web-handoff" "$(cat .gitignore 2>/dev/null)"
want "origin 记录了 harness" '"harness"' "$(cat .chatgpt/web-handoff/$JOB/job.json)"
want "单活跃作业拦截" '"error": "busy"' \
     "$("$CGH" new --action review --subject "第二个作业应该被拦住" 2>&1)"

echo "== 3. 状态机 =="
want "created→completed 应拒" '"error": "bad_transition"' "$("$CGH" update --id "$JOB" --set status=completed 2>&1)"
want "created→ui_changed 应放行" '"status": "ui_changed"'  "$("$CGH" update --id "$JOB" --set status=ui_changed 2>&1)"
want "终态→generating 应拒"     '"error": "terminal"'      "$("$CGH" update --id "$JOB" --set status=generating 2>&1)"

echo "== 4. 哨兵解析 =="
mk(){ printf 'CGH_RESULT_%s\nverdict: %s\nconfidence: %s\nsummary: %s\nfindings:\n- none\nrecommended_actions:\n- none\nmissing_information:\n- none\nCGH_END_%s\n' "$JOB" "$2" "$3" "$4" "$JOB" > "$WORK/$1"; }
mk decoy.txt reject 0.1 "诱饵不该被取到"
mk last.txt  pass   0.9 "应该取到这一条"
cat "$WORK/decoy.txt" "$WORK/last.txt" > "$WORK/both.txt"
want "重复哨兵取最后一处" "应该取到这一条" "$("$CGH" parse --id "$JOB" --from "$WORK/both.txt" 2>&1)"

printf '完全没有哨兵\n' > "$WORK/a.txt"
printf 'CGH_RESULT_%s\nverdict: pass\n' "$JOB" > "$WORK/b.txt"
printf 'CGH_RESULT_%s\nverdict: 乱写\nconfidence: 0.9\nsummary: x\nCGH_END_%s\n' "$JOB" "$JOB" > "$WORK/c.txt"
printf 'CGH_RESULT_%s\nverdict: pass\nconfidence: 9.9\nsummary: x\nCGH_END_%s\n' "$JOB" "$JOB" > "$WORK/d.txt"
printf 'CGH_RESULT_%s\nverdict: pass\nconfidence: 0.9\nsummary:\nCGH_END_%s\n' "$JOB" "$JOB" > "$WORK/e.txt"
for f in a b c d e; do
  want "畸形哨兵 $f 应判 no_sentinel" "no_sentinel" "$("$CGH" parse --id "$JOB" --from "$WORK/$f.txt" 2>&1)"
done

echo "== 5. 内容门禁 =="
want "审查对象过短应拒" '"error": "no_subject"' "$("$CGH" new --action review --subject "太短" 2>&1)"
want "未知档位应拒"     '"error": "bad_effort"' "$("$CGH" new --action review --effort 不存在的档 --subject "档位应该被拒绝的作业" 2>&1)"

echo "== 6. abort 释放槽位 =="
# 上面的 parse 已把 $JOB 推成 no_sentinel 终态，abort 终态作业本就该拒 —— 另起一个来测
want "abort 终态作业应拒" '"error": "terminal"' "$("$CGH" abort --id "$JOB" --reason "干跑" 2>&1)"
"$CGH" new --action review --subject "专门用来测 abort 的作业对象" >/dev/null 2>&1
LIVE=$("$CGH" state 2>&1 | grep -o 'id=[a-z0-9_]*' | cut -d= -f2)
want "abort 活跃作业成功" '"ok": true' "$("$CGH" abort --id "$LIVE" --reason "干跑" 2>&1)"
want "abort 后槽位已释放" '"ok": true' "$("$CGH" new --action review --subject "abort 之后应该能建新作业" 2>&1)"

echo "== 7. 账本与统计 =="
want "账本已落盘" '"ev"' "$(cat "$CGH_LEDGER" 2>/dev/null | head -1)"
want "stats 能出表" "按档位" "$("$CGH" stats 2>&1)"

echo
printf '通过 %s，失败 %s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
echo "干跑全绿。⚠️ 但浏览器那一半没测到 —— 合入前请真跑一次低档位作业。"
