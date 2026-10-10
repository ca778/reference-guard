"""Explicit minimal paid engine verification. Does not edit the user's engine config."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import time
import tomllib
from pathlib import Path
import pymupdf
from reference_guard.compatibility import ROOT, fingerprint
from reference_guard.config import load_config
from tests.test_detector import pdf, BODY, REFS


def verify(original: Path, output: Path, mode: str) -> dict:
    with pymupdf.open(original) as source, pymupdf.open(output) as out:
        expected = len(source) * (2 if mode=='dual_alternating' else 1)
        assert len(out)==expected, f'{mode}: missing pages'
        source_text=source[-1].get_text()
        # Compare all reference words, DOI, page mapping, geometry, pixels and links.
        indices=[2,3] if mode=='dual_alternating' else [1]
        for idx in indices:
            text=out[idx].get_text()
            assert all(word in text for word in source_text.split()), f'{mode}: missing reference text'
            assert '10.1234/test' in text
        srcpix=source[1].get_pixmap()
        for idx in indices:
            page=out[idx]
            if mode=='dual_lr':
                assert page.rect.width==source[1].rect.width*2
                for clip in [pymupdf.Rect(0,0,600,800),pymupdf.Rect(600,0,1200,800)]:
                    pix=page.get_pixmap(clip=clip)
                    assert pix.samples==srcpix.samples, 'Reference pixels changed'
            else:
                assert page.rect==source[1].rect
                assert page.get_pixmap().samples==srcpix.samples, 'Reference pixels changed'
        links=[l.get('uri') for l in source[1].get_links() if 'uri' in l]
        retained=[l.get('uri') for idx in indices for l in out[idx].get_links() if 'uri' in l]
        link_status='PASS' if all(uri in retained for uri in links) else 'FAIL'
        return {'status':'PASS' if link_status=='PASS' else 'PARTIAL','pages':len(out),'reference_text':'PASS',
                'reference_pixels':'PASS','links':link_status,'source_links':links,'output_links':retained,
                'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--allow-api',action='store_true')
    args=parser.parse_args()
    if not args.allow_api:
        raise SystemExit('Real translation requires --allow-api; may incur API costs')
    cfg=load_config()
    output=ROOT/'artifacts'/'engine-verification'; output.mkdir(parents=True,exist_ok=True)
    source=output/'reference-guard-minimal.pdf'
    if not source.exists():
        source.write_bytes(pdf([BODY,'References\n'+REFS]))
        with pymupdf.open(source) as d:
            d[1].insert_link({'kind':pymupdf.LINK_URI,'from':pymupdf.Rect(45,85,370,110),'uri':'https://doi.org/10.1234/test'})
            d.save(str(output/'linked.pdf'))
        source=output/'linked.pdf'
    else:
        source=output/'linked.pdf'
    engine_config=Path(cfg['server_dir'])/'config'/'config.toml'
    engine_settings=tomllib.loads(engine_config.read_text(encoding='utf-8'))
    assert engine_settings.get('pdf',{}).get('only_include_translated_page') is False
    # Never emit or store key/token values. Redact known secrets in subprocess output.
    secrets=[str(v) for s in engine_settings.values() if isinstance(s,dict) for k,v in s.items()
             if any(word in k.lower() for word in ['key','token','password','authorization']) and v]
    report={'timestamp':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'selected_pages':'1-1','only_include_translated_page':False,'seed':'N/A','service':'deepseek','modes':{},'commands':[]}
    for mode in ['dual_lr','dual_alternating']:
        folder=output/mode; folder.mkdir(exist_ok=True)
        command=[str(Path(cfg['server_python']).with_name('pdf2zh_next.exe')),str(source),'--deepseek',
                 '--config-file',str(engine_config),'--pages','1-1','--output',str(folder),'--lang-in','en','--lang-out','zh-CN',
                 '--no-auto-extract-glossary','--watermark-output-mode','no_watermark']
        if mode=='dual_alternating': command.append('--use-alternating-pages-dual')
        report['commands'].append(command)
        print(f'Running {mode}: one selected body page (second run reuses translation cache)',flush=True)
        completed=subprocess.run(command,capture_output=True,timeout=300)
        log=(completed.stdout+completed.stderr).decode('utf-8',errors='replace')
        for secret in sorted(secrets,key=len,reverse=True): log=log.replace(secret,'[REDACTED]')
        (folder/'engine.log').write_text(log,encoding='utf-8')
        if completed.returncode:
            report['modes'][mode]={'status':'FAIL','exit_code':completed.returncode}
            print(f'{mode}: engine failed; inspect sanitized log',flush=True)
            break
        mono=next(folder.glob('*.mono.pdf')); dual=next(folder.glob('*.dual.pdf'))
        report['modes']['mono']=verify(source,mono,'mono')
        report['modes'][mode]=verify(source,dual,mode)
        with pymupdf.open(dual) as d:
            for index in [0,len(d)-1]:
                d[index].get_pixmap(matrix=pymupdf.Matrix(.7,.7)).save(str(folder/f'preview-{index+1}.png'))
        print(json.dumps(report['modes'][mode],ensure_ascii=False),flush=True)
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    # Text+page+pixel PASS is sufficient for page safety. Link loss must be separately disclosed.
    if all(report['modes'].get(m,{}).get('reference_pixels')=='PASS' for m in ['mono','dual_lr','dual_alternating']):
        validation={'fingerprint':fingerprint(cfg),'modes':{m:'PASS' for m in ['mono','dual_lr','dual_alternating']},
                    'output_report':str(output/'report.json'),'link_limitations':{m:d['links'] for m,d in report['modes'].items()}}
        (ROOT/cfg['validation_file']).write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__': main()
