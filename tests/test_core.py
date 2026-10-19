import copy
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from collector.aggregate import aggregate
from collector.indexer import Indexer
from collector.pricing import PriceBook, validate
from collector.timeutil import window, parse_time
from collector.tokens import normalize
from tests.fixtures.factory import usage, sum_usage, meta, context, count, event, write, response

ROOT = Path(__file__).resolve().parent.parent


class CoreTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "tests" / "output").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "tests" / "output")
        self.root = Path(self.tmp.name)
        self.home = self.root / "中文 home"
        self.path = self.home / "sessions" / "2026" / "10" / "13" / "old.jsonl"
        self.index = Indexer(self.root / "cache.sqlite3", [self.home])
        self.prices = PriceBook(ROOT / "pricing" / "official-standard.json")

    def tearDown(self):
        self.index.close()
        self.tmp.cleanup()

    def result(self, **options):
        self.index.scan_all()
        result = aggregate(self.index, self.prices, day="2026-10-14", **options)
        json.dumps(result)  # Contract must remain serializable for unpriced/internal models too.
        return result

    def test_native_fork_replayed_parent_header_does_not_change_owner(self):
        a, b = usage(), usage(200, 40)
        write(self.path, [meta('p'), context(), response('p', 'parent', value=a)])
        child = self.path.with_name('child.jsonl')
        write(child, [meta('c', parent_thread_id='p', forked_from_id='p'), meta('p'),
            context(), response('p', 'parent', value=a), count(a, a),
            context('gpt-6-astra', 'child-turn'),
            response('c', 'child', 'child-turn', b, sum_usage(a,b), '2026-10-14T02:00:00Z'),
            count(sum_usage(a,b), b, '2026-10-14T02:00:01Z')])
        result = self.result()
        self.assertEqual(result['totals']['total'], 320)
        self.assertEqual(result['dataStatus'], 'complete')
        self.assertEqual({m['modelId']:m['totals']['total'] for m in result['models']},
            {'gpt-6.1-sol':110, 'gpt-6-astra':210})
        self.assertEqual(self.index.db.execute('SELECT sid FROM files WHERE path=?', (str(child),)).fetchone()[0], 'c')

    def test_native_response_ids_dedupe_and_context_estimates_are_not_billed(self):
        a = usage()
        write(self.path, [meta(), context(), count(a,a), response(value=a),
            count(usage(0,0,0,0,0), usage(0,0,0,0,0), '2026-10-14T01:01:00Z'),
            response(value=a, ts='2026-10-14T01:02:00Z')])
        result = self.result()
        self.assertEqual(result['totals']['total'], 110)
        self.assertEqual(result['dataStatus'], 'complete')
        self.assertEqual(self.index.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0], 1)

    def test_native_ownership_needs_no_missing_ancestor_baseline(self):
        write(self.path, [meta(forked_from_id='unavailable'), context(), response()])
        result = self.result()
        self.assertEqual(result['totals']['total'], 110)
        self.assertEqual(result['dataStatus'], 'complete')

    def test_old_issues_do_not_invalidate_today_but_reappear_on_their_day(self):
        a, b = usage(1000,200), usage()
        write(self.path, [meta(cli_version='unverified'), context(),
            count(a,a,'2026-10-12T01:00:00Z'), count(b,b,'2026-10-12T02:00:00Z')])
        write(self.path.with_name('today.jsonl'), [meta('today'), context(), response('today')])
        today = self.result()
        self.assertEqual(today['dataStatus'], 'complete')
        self.assertEqual(today['diagnostics'], [])
        past = aggregate(self.index, self.prices, day='2026-10-12')
        self.assertEqual(past['dataStatus'], 'partial')
        self.assertIn('counter_decreased', {d['code'] for d in past['diagnostics']})

    def test_exact_reviewed_native_version_and_future_version(self):
        write(self.path, [meta(cli_version='0.160.1'), context(), response()])
        self.assertEqual(self.result()['priceStatus'], 'complete')
        write(self.path, [meta(cli_version='0.999.0'), context(), response()])
        result = self.result()
        self.assertEqual(result['dataStatus'], 'partial')
        self.assertEqual(result['totals']['total'], 110)
        self.assertIsNone(result['totalCostUSD'])

    def test_reviewed_0163_response_usage_survives_parser_upgrade(self):
        from unittest.mock import patch
        from collector.indexer import SUPPORTED_VERSIONS
        version = '0.163.0-alpha.10.2'
        write(self.path, [meta(cli_version=version), context(), count(), response(),
            response(ts='2026-10-14T01:02:00Z')])
        with patch('collector.indexer.SUPPORTED_VERSIONS', SUPPORTED_VERSIONS - {version}):
            self.assertEqual(self.result()['dataStatus'], 'partial')
        self.index.db.execute("UPDATE settings SET value='5' WHERE key='parser'")
        self.index.db.commit()
        self.index.close()
        self.index = Indexer(self.root / 'cache.sqlite3', [self.home])
        result = self.result()
        self.assertEqual(result['totals']['total'], 110)
        self.assertEqual(result['dataStatus'], 'complete')
        self.assertEqual(result['priceStatus'], 'complete')
        self.assertEqual(result['diagnostics'], [])

    def test_conflicting_native_response_ids_remain_unpriced(self):
        write(self.path, [meta(), context(), response(),
            response(value=usage(200,40), ts='2026-10-14T01:01:00Z')])
        result = self.result()
        self.assertEqual(result['totals']['total'], 110)
        self.assertEqual(result['dataStatus'], 'partial')
        self.assertIsNone(result['totalCostUSD'])
        self.assertIn('conflicting_response_usage', {d['code'] for d in result['diagnostics']})

    def test_native_stream_preserves_an_identified_legacy_prefix(self):
        a, b = usage(), usage(200,40)
        write(self.path, [meta(), context(), count(a,a),
            response(value=b,total=sum_usage(a,b),ts='2026-10-14T02:00:00Z'),
            count(sum_usage(a,b),b,'2026-10-14T02:00:01Z')])
        self.assertEqual(self.result()['totals']['total'], 320)

    def test_native_missing_prefix_is_visible_without_counting_inherited_totals(self):
        a, b = usage(), usage(200,40)
        write(self.path, [meta(), context(), response(value=b,total=sum_usage(a,b))])
        result = self.result()
        self.assertEqual(result['totals']['total'], 210)
        self.assertEqual(result['dataStatus'], 'partial')
        self.assertIn('unverified_initial_snapshot', {d['code'] for d in result['diagnostics']})

    def test_native_appended_after_context_snapshot_does_not_double_count(self):
        write(self.path, [meta(), context(), count()])
        self.assertEqual(self.result()['totals']['total'], 110)
        write(self.path, [response(ts='2026-10-14T01:00:01Z')], mode='a')
        self.assertEqual(self.result()['totals']['total'], 110)

    def test_native_missing_turn_model_is_not_guessed(self):
        write(self.path, [meta(), context('gpt-6-astra', 'unrelated'), response()])
        result = self.result()
        self.assertEqual(result['models'][0]['modelId'], 'unknown')
        self.assertIsNone(result['totalCostUSD'])

    def test_native_media_and_explicit_compaction_replacement(self):
        write(self.path, [meta(), context(),
            event('response_item', {'type':'message','content':[{'type':'input_image','image_url':'private://image'}]}, '2026-10-14T00:59:00Z'),
            response(), event('compacted', {'replacement_history':[{'type':'message','content':[{'type':'input_text','text':'private summary'}]}]}, '2026-10-14T01:01:00Z'),
            response(rid='response2', ts='2026-10-14T01:02:00Z')])
        result = self.result()
        self.assertEqual(result['dataStatus'], 'complete')
        self.assertEqual(result['pricedTokens'], 220)
        self.assertEqual(result['unpricedTokens'], 0)
        cache = '\n'.join(r[0] for r in self.index.db.execute('SELECT data FROM evidence'))
        self.assertNotIn('private://image', cache)
        self.assertNotIn('private summary', cache)

    def test_non_fork_mismatched_header_is_not_silently_accepted(self):
        write(self.path, [meta(), meta('unexpected'), context(), count()])
        result = self.result()
        self.assertEqual(result['dataStatus'], 'partial')
        self.assertIn('conflicting_session_metadata', {d['code'] for d in result['diagnostics']})

    def test_image_input_uses_reported_tokens_once_for_all_reviewed_models(self):
        for model, expected in [('gpt-6.1-sol', '0.000262'), ('gpt-6-astra', '0.00132'), ('gpt-6-luna', '0.0000132')]:
            with self.subTest(model=model):
                write(self.path, [meta(), context(model), event('response_item',
                    {'type':'message','content':[{'type':'input_image','detail':'original','image_url':'private://pixels'}]},
                    '2026-10-14T00:59:01Z'), response()])
                result = self.result()
                self.assertEqual(Decimal(result['totalCostUSD']), Decimal(expected))
                self.assertEqual(result['priceCoverage'], '1')
                self.assertEqual(result['totals']['total'], 110)

    def test_image_input_long_context_whole_request_boundary(self):
        for n, expected in [(272000, '0.364'), (272001, '0.723004')]:
            with self.subTest(n=n):
                write(self.path, [meta(), context(), count(usage(n,100000,0,1000), modality='image-input')])
                self.assertEqual(Decimal(self.result()['totalCostUSD']), Decimal(expected))

    def test_audio_output_image_and_ambiguous_image_remain_unpriced(self):
        for kind in ('input_audio','output_audio','output_image','image','input_video'):
            with self.subTest(kind=kind):
                write(self.path, [meta(), context(), event('response_item',
                    {'type':'message','content':[{'type':kind}]}, '2026-10-14T00:59:01Z'), response()])
                result = self.result()
                self.assertEqual(result['dataStatus'], 'complete')
                self.assertEqual(result['unpricedTokens'], 110)
                self.assertIsNone(result['totalCostUSD'])

    def test_later_image_does_not_clear_audio_until_explicit_compaction(self):
        write(self.path, [meta(), context(),
            event('response_item', {'type':'message','content':[{'type':'input_audio'}]}, '2026-10-14T00:59:01Z'),
            event('response_item', {'type':'message','content':[{'type':'input_image'}]}, '2026-10-14T00:59:02Z'),
            response(), event('compacted', {'replacement_history':[{'type':'message','content':[{'type':'input_image'}]}]}, '2026-10-14T01:01:00Z'),
            response(rid='r2', ts='2026-10-14T01:02:00Z')])
        result = self.result()
        self.assertEqual((result['pricedTokens'], result['unpricedTokens']), (110,110))

    def test_image_policy_is_explicit_and_never_bypasses_other_errors(self):
        write(self.path, [meta(), context(), count(modality='image-input')])
        self.result()
        record = json.loads(self.index.db.execute('SELECT data FROM requests').fetchone()[0])
        book = PriceBook(ROOT / 'pricing/official-standard.json')
        del book.table['models'][0]['imageInputPricing']
        self.assertEqual(book.cost(record)[1], 'unsupported_modality')
        record['errors'] = ['unverified_log_version']
        self.assertEqual(self.prices.cost(record)[1], 'unverified_log_version')
        record['errors'] = []
        record['usage']['cacheRead'] = None
        self.assertEqual(self.prices.cost(record)[1], 'missing_cache_classification')

    def test_image_unknown_model_stays_unknown(self):
        write(self.path, [meta(), context('unreviewed-vision'), count(modality='image-input')])
        result = self.result()
        self.assertIsNone(result['totalCostUSD'])
        self.assertIn('unknown_model', {d['code'] for d in result['diagnostics']})

    def test_invalid_image_policy_rejected(self):
        table = copy.deepcopy(self.prices.table)
        table['models'][0]['imageInputPricing'] = 'multiply-by-1.2-again'
        with self.assertRaises(ValueError):
            validate(table)

    def test_parser_upgrade_rebuilds_incorrect_ownership_cache(self):
        write(self.path, [meta(), context(), response()])
        self.result()
        self.index.db.execute("UPDATE settings SET value='3' WHERE key='parser'")
        self.index.db.commit()
        self.index.close()
        self.index = Indexer(self.root / 'cache.sqlite3', [self.home])
        self.assertEqual(self.index.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0], 0)
        self.assertEqual(self.result()['totals']['total'], 110)

    def test_model_switch_repeat_and_equal_distinct_requests(self):
        a, b = usage(), usage()
        write(self.path, [meta(), context(), count(a,a,response_id="r1"), count(a,a,ts="2026-10-14T01:00:01Z"),
            context("gpt-6-astra", "t2", "2026-10-14T01:01:00Z"), count(sum_usage(a,b),b,ts="2026-10-14T01:02:00Z",response_id="r2")])
        r = self.result()
        self.assertEqual(r["totals"]["total"], 220)
        self.assertEqual({m["modelId"]:m["totals"]["total"] for m in r["models"]}, {"gpt-6.1-sol":110,"gpt-6-astra":110})
        before = r["knownSubtotalUSD"]
        self.index.close()
        self.index = Indexer(self.root / "cache.sqlite3", [self.home])
        self.assertEqual(self.result()["knownSubtotalUSD"], before)

    def test_stable_response_replay_with_different_timestamp(self):
        a = usage()
        write(self.path, [meta(),context(),count(a,a,response_id="r1"),count(sum_usage(a,a),a,ts="2026-10-14T01:01:00Z",response_id="r1")])
        self.assertEqual(self.result()["totals"]["total"], 110)

    def test_artifact_case_exact_decimal(self):
        a = usage(100000,60000,0,10000,4000)
        write(self.path,[meta(),context(),count(a,a)])
        r = self.result()
        self.assertEqual(r["totals"]["total"],110000)
        self.assertEqual(Decimal(r["totalCostUSD"]),Decimal("0.186"))
        self.assertEqual(r["totals"]["reasoning"],4000)

    def test_threshold_per_request_and_not_daily_sum(self):
        for n,expected in [(272000,"0.544"),(272001,"1.088004")]:
            a=usage(n,0,0,0,0)
            write(self.path,[meta(),context(),count(a,a)])
            self.assertEqual(Decimal(self.result()["totalCostUSD"]),Decimal(expected))
        a=usage(200000,0,0,100,0)
        write(self.path,[meta(),context(),count(a,a),count(sum_usage(a,a),a,ts="2026-10-14T02:00:00Z")])
        self.assertEqual(Decimal(self.result()["totalCostUSD"]),Decimal("0.802"))

    def test_threshold_applies_to_all_categories(self):
        a=usage(272001,100000,1000,10000,0)
        write(self.path,[meta(),context(),count(a,a)])
        expected=Decimal(171001*4+100000*.2+1000*5+10000*15)/1000000
        self.assertEqual(Decimal(self.result()["totalCostUSD"]),expected)

    def test_unknown_model_keeps_tokens_partial_price(self):
        a=usage()
        write(self.path,[meta(),context(),count(a,a),context("gpt-6.1-sol-unverified-suffix","t2","2026-10-14T01:01:00Z"),count(sum_usage(a,a),a,ts="2026-10-14T01:02:00Z")])
        r=self.result()
        self.assertEqual(r["totals"]["total"],220)
        self.assertIsNone(r["totalCostUSD"])
        self.assertEqual(r["unpricedTokens"],110)
        self.assertIsNotNone(r["knownSubtotalUSD"])
        self.assertEqual(r["dataStatus"],"complete")

    def test_missing_model_and_reroute(self):
        write(self.path,[meta(),count(),context(ts="2026-10-14T01:01:00Z"),count(sum_usage(usage(),usage()),usage(),ts="2026-10-14T01:02:00Z",actual_model="gpt-6-astra")])
        r=self.result()
        self.assertEqual({m["modelId"] for m in r["models"]},{"unknown","gpt-6-astra"})

    def test_beijing_midnight_and_old_directory(self):
        a=usage()
        write(self.path,[meta(),context(ts="2026-10-13T15:58:00Z"),count(a,a,"2026-10-13T15:59:59Z"),count(sum_usage(a,a),a,"2026-10-13T16:00:00Z")])
        self.assertEqual(self.result()["totals"]["total"],110)
        self.assertEqual(window("2026-10-14")[1],"2026-10-13T16:00:00+00:00")
        with self.assertRaises(ValueError):parse_time("2026-10-14T00:00:00")

    def test_fork_baseline_no_inherited_count(self):
        a=usage()
        write(self.path,[meta("p"),context(),count(a,a,"2026-10-13T01:00:00Z")])
        child=self.path.with_name("child.jsonl")
        write(child,[meta("c",forked_from_id="p",timestamp="2026-10-13T01:01:00Z"),context(),count(sum_usage(a,a),a)])
        self.assertEqual(self.result()["totals"]["total"],110)

    def test_missing_fork_ancestor_quarantine_then_delta(self):
        a=usage()
        write(self.path,[meta("c",forked_from_id="missing"),context(),count(a,a),count(sum_usage(a,a),a,"2026-10-14T02:00:00Z")])
        r=self.result()
        self.assertEqual(r["totals"]["total"],110)
        self.assertEqual(r["dataStatus"],"partial")
        self.assertIn("missing_ancestor",{d["code"] for d in r["diagnostics"]})

    def test_child_found_before_parent_and_later_ancestor(self):
        a=usage()
        write(self.path,[meta("c",forked_from_id="p"),context(),count(sum_usage(a,a),a)])
        self.assertEqual(self.result()["totals"]["total"],0)
        write(self.path.with_name("parent.jsonl"),[meta("p"),context(ts="2026-10-12T00:00:00Z"),count(a,a,"2026-10-12T01:00:00Z")])
        self.assertEqual(self.result()["totals"]["total"],110)

    def test_work_child_and_guardian_scope(self):
        a=usage()
        write(self.path,[meta("p"),context(),count(a,a)])
        write(self.path.with_name("work.jsonl"),[meta("w",originator="worker",parent_thread_id="p",source={"subagent":{"spawn":{"parent_thread_id":"p"}}}),context(),count(a,a)])
        write(self.path.with_name("guardian.jsonl"),[meta("g",parent_thread_id="p",source={"subagent":{"other":"guardian"}}),context("codex-auto-review"),count(a,a)])
        r=self.result()
        self.assertEqual(r["totals"]["total"],220)
        self.assertEqual(r["internalModels"][0]["totals"]["total"],110)
        self.assertEqual(self.result(include_internal=True)["totals"]["total"],330)
        write(self.path,[meta("p",usage_includes_subagents=True),context(),count(a,a)])
        self.assertEqual(self.result()["totals"]["total"],110)

    def test_sources_not_vscode_alone(self):
        write(self.path,[meta(originator="IDE"),context(),count()])
        self.assertEqual(self.result()["totals"]["total"],0)
        self.assertEqual(self.result(include_other=True)["totals"]["total"],110)
        write(self.path,[meta(originator="codex_cli_rs",source="cli"),context(),count()])
        self.assertEqual(self.result(include_cli=True)["totals"]["total"],110)

    def test_partial_line_bad_line_truncation_same_length_rewrite(self):
        write(self.path,[meta(),context()])
        line=json.dumps(count())+"\n"
        with self.path.open("a",encoding="utf-8") as f:f.write(line[:30])
        r=self.result();self.assertEqual(r["totals"]["total"],0);self.assertEqual(r["dataStatus"],"partial")
        with self.path.open("a",encoding="utf-8") as f:f.write(line[30:])
        self.assertEqual(self.result()["totals"]["total"],110)
        with self.path.open("a",encoding="utf-8") as f:f.write("BROKEN\n")
        self.assertEqual(self.result()["dataStatus"],"partial")
        write(self.path,[meta(),context(),count()])
        self.assertEqual(self.result()["dataStatus"],"complete")
        original=self.path.read_text()
        self.path.write_text(original.replace("gpt-6.1-sol","gpt-6-astra"),encoding="utf-8")
        self.assertEqual(self.result()["models"][0]["modelId"],"gpt-6-astra")

    def test_copy_archive_cross_home_and_missing_file(self):
        write(self.path,[meta(),context(),count()])
        self.result()
        archive=self.home / "archived_sessions" / "copy.jsonl"
        archive.parent.mkdir(parents=True)
        shutil.copyfile(self.path,archive)
        self.assertEqual(self.result()["totals"]["total"],110)
        other=self.root / "other" / "sessions" / "copy.jsonl"
        other.parent.mkdir(parents=True);shutil.copyfile(self.path,other)
        self.index.homes.append(str(self.root / "other"))
        self.assertEqual(self.result()["totals"]["total"],110)
        self.path.unlink();self.assertEqual(self.result()["totals"]["total"],110)
        archive.unlink();other.unlink();self.assertEqual(self.result()["totals"]["total"],0)

    def test_incremental_reads_only_appended_bytes(self):
        write(self.path,[meta(),context(),count()])
        self.result();before=self.index.bytes_read
        self.result();self.assertEqual(before,self.index.bytes_read)
        write(self.path,[count(sum_usage(usage(),usage()),usage(),"2026-10-14T02:00:00Z")],"a")
        self.assertEqual(self.result()["totals"]["total"],220)
        self.assertLess(self.index.bytes_read-before,self.path.stat().st_size)

    def test_reset_cannot_silently_clamp(self):
        a=usage();b=usage(5,1,0,2,1)
        write(self.path,[meta(),context(),count(a,a),count(b,b,"2026-10-14T01:02:00Z"),count(sum_usage(b,b),b,"2026-10-14T01:03:00Z")])
        r=self.result();self.assertEqual(r["totals"]["total"],117);self.assertEqual(r["dataStatus"],"partial")
        write(self.path,[meta(),context(),count(a,a),count(b,b,"2026-10-14T01:02:00Z",usage_reset=True)])
        self.assertEqual(self.result()["totals"]["total"],117)

    def test_multi_request_delta_keeps_tokens_unpriced(self):
        a=usage()
        write(self.path,[meta(),context(),count(a,a),count(sum_usage(a,a,a),a,"2026-10-14T02:00:00Z")])
        r=self.result();self.assertEqual(r["totals"]["total"],330);self.assertEqual(r["unpricedTokens"],220)

    def test_write_semantics_and_missing_categories(self):
        a=usage(100,20,10,10,4)
        normalized,errors=normalize(a,"included")
        self.assertEqual(normalized["uncachedInput"],70);self.assertFalse(errors)
        self.assertIn("unknown_cache_write_semantics",normalize(a)[1])
        write(self.path,[meta(cli_version="0.162.0-alpha.17.2"),context(),count(a,a)])
        r=self.result();self.assertEqual(r["totals"]["total"],110);self.assertIsNone(r["totalCostUSD"])
        a.pop("cached_input_tokens")
        write(self.path,[meta(),context(),count(a,a)])
        self.assertIsNone(self.result()["totals"]["cacheRead"])
        a=usage();a["cached_input_tokens"]=101
        write(self.path,[meta(),context(),count(a,a)])
        self.assertEqual(self.result()["dataStatus"],"partial")

    def test_price_update_and_corrupt_last_good_restart(self):
        path=self.root/"prices.json";backup=self.root/"good.json"
        table=json.loads((ROOT/"pricing"/"official-standard.json").read_text())
        path.write_text(json.dumps(table));self.prices=PriceBook(path,backup)
        write(self.path,[meta(),context(),count()])
        before=self.result();table["models"][0]["rates"]["output"]="20"
        path.write_text(json.dumps(table));self.prices.reload();after=self.result()
        self.assertEqual(before["totals"],after["totals"]);self.assertNotEqual(before["knownSubtotalUSD"],after["knownSubtotalUSD"])
        path.write_text("broken");self.prices.reload();self.assertEqual(self.result()["knownSubtotalUSD"],after["knownSubtotalUSD"])
        self.prices=PriceBook(path,backup);self.assertEqual(self.result()["knownSubtotalUSD"],after["knownSubtotalUSD"])
        table["models"][0]["rates"]["output"]="NaN"
        with self.assertRaises(ValueError):validate(table)

    def test_no_private_body_in_cache(self):
        sentinel="PRIVATE SYNTHETIC SECRET SHOULD NOT PERSIST"
        write(self.path,[meta(),context(),event("response_msg",{"type":"message","content":sentinel}),count()])
        self.result()
        for row in self.index.db.execute("SELECT data FROM evidence"):
            self.assertNotIn(sentinel,row[0])
        self.assertEqual(self.result()["dataStatus"],"complete")

    def test_first_index_unavailable_and_zero_usage(self):
        self.assertEqual(aggregate(self.index,self.prices,day="2026-10-14")["dataStatus"],"indexing")
        self.assertEqual(self.result()["dataStatus"],"unavailable")
        self.path.parent.mkdir(parents=True)
        r=self.result();self.assertEqual(r["dataStatus"],"complete");self.assertEqual(r["totalCostUSD"],"0")

    def test_unsupported_version_unknown_cache_not_zero(self):
        write(self.path,[meta(cli_version="unverified"),context(),count()])
        r=self.result();self.assertEqual(r["totals"]["total"],110);self.assertEqual(r["dataStatus"],"partial");self.assertIsNone(r["totalCostUSD"])

    def test_invalid_numeric_fields_do_not_crash_later_delta(self):
        a=usage();b=sum_usage(a,a);b["cached_input_tokens"]="invalid"
        write(self.path,[meta(),context(),count(a,a),count(b,a,"2026-10-14T02:00:00Z")])
        r=self.result();self.assertEqual(r["totals"]["total"],220);self.assertEqual(r["dataStatus"],"partial")
        self.assertIsNone(r["totalCostUSD"])

    def test_first_snapshot_cannot_add_unverified_inherited_total(self):
        a=usage()
        write(self.path,[meta(),context(),count(sum_usage(a,a,a),a)])
        r=self.result();self.assertEqual(r["totals"]["total"],110);self.assertEqual(r["dataStatus"],"partial")

    def test_unknown_request_boundary_and_zero_priced_internal_json(self):
        write(self.path,[meta("g",parent_thread_id="absent",source={"subagent":{"other":"guardian"}}),context("codex-auto-review"),count()])
        r=self.result();self.assertEqual(r["totals"]["total"],0);self.assertEqual(r["knownSubtotalUSD"],"0")
        self.assertIsNone(r["internalModels"][0]["knownSubtotalUSD"])

    def test_multimodal_flag_without_private_image_content(self):
        write(self.path,[meta(),context(),event("response_msg",{"type":"message","content":[{"type":"input_image","image_url":"private-synthetic-image"}]},"2026-10-14T00:59:59Z"),count()])
        r=self.result();self.assertEqual(r["totals"]["total"],110);self.assertEqual(r["priceStatus"],"complete")
        self.assertEqual(Decimal(r["totalCostUSD"]),Decimal('0.000262'))
        self.assertFalse(any("private-synthetic-image" in row[0] for row in self.index.db.execute("SELECT data FROM evidence")))

    def test_windows_new_file_signal(self):
        import time
        write(self.path,[meta(),context(),count()]);self.result()
        if not self.index.signals.handles:self.skipTest("Directory notification unavailable; periodic fallback used")
        write(self.path.with_name("new.jsonl"),[meta("new"),context(),count()])
        for _ in range(20):
            self.index.scan()
            r=aggregate(self.index,self.prices,day="2026-10-14")
            if r["totals"]["total"]==220:break
            time.sleep(.025)
        self.assertEqual(r["totals"]["total"],220)

    def test_bad_metadata_line_is_diagnosed_and_later_lines_continue(self):
        write(self.path,[meta(),context(),event("turn_context",{"model":{"invalid":"shape"},"turn_id":"bad"}),count()])
        r=self.result();self.assertEqual(r["totals"]["total"],110);self.assertEqual(r["dataStatus"],"partial")
        self.assertIn("bad_line",{d["code"] for d in r["diagnostics"]})

    def test_fork_cycle_remains_pending(self):
        write(self.path,[meta("a",forked_from_id="b"),context(),count()])
        write(self.path.with_name("b.jsonl"),[meta("b",forked_from_id="a"),context(),count()])
        r=self.result();self.assertEqual(r["totals"]["total"],0);self.assertEqual(r["dataStatus"],"partial")
        self.assertIn("ancestor_cycle",{d["code"] for d in r["diagnostics"]})


if __name__=="__main__":unittest.main()
