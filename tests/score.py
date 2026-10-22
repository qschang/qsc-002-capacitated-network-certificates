#!/usr/bin/env python3
import argparse, json, xml.etree.ElementTree as ET
p=argparse.ArgumentParser(); p.add_argument('--config',required=True); p.add_argument('--junit',required=True); p.add_argument('--report-out',required=True); p.add_argument('--reward-out',required=True); a=p.parse_args()
root=ET.parse(a.junit).getroot(); cfg=json.load(open(a.config,encoding='utf-8')); expected=sum(int(g['expected_count']) for g in cfg['groups'])
ok=(int(root.attrib.get('tests','-1'))==expected and all(int(root.attrib.get(k,'0'))==0 for k in ('failures','errors','skipped')))
score=1.0 if ok else 0.0
json.dump({'score':score,'expected_tests':expected,'observed_tests':int(root.attrib.get('tests','-1'))},open(a.report_out,'w'),sort_keys=True)
open(a.reward_out,'w').write(f'{score:.3f}\n')
raise SystemExit(0 if ok else 1)
