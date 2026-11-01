"""Offline report; source values are escaped and never interpreted as HTML."""
from html import escape

def esc(value): return escape(str(value),quote=True)
def table(rows, keys):
    head=''.join('<th>'+esc(k.replace('_',' '))+'</th>' for k in keys)
    body=''.join('<tr>'+''.join('<td>'+esc(r.get(k,'—'))+'</td>' for k in keys)+'</tr>' for r in rows)
    return '<div class="scroll"><table><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody></table></div>'

def render(data):
    entries=data['entries'];groups=data['groups'];sections=[]
    for e in entries:
        sample=e['sample'];segment=e['segment']
        tiles=[]
        for g in groups:
            if (g['sample'],g['segment']) != (sample,segment):continue
            bars=[]
            for r in sorted(g['rows'],key=lambda r:float(r['abundance']),reverse=True):
                pct=float(r['abundance'])*100
                bars.append(f'<div class="barrow"><span>{esc(r["id"])}</span><div class="track"><i style="width:{pct:.6f}%"></i></div><strong>{pct:.1f}%</strong></div>')
            residual=g['unresolved_abundance']*100;unassigned=g['unassigned_abundance']*100
            tiles.append(f'''<article class="group"><div class="grouphead"><h3>{esc(g['id'])}</h3><span class="pill">{esc(g['method'])} · declared</span></div>
<p>Positions <b>{esc(g['span'])}</b> · denominator <b>{g['denominator']:,} {esc(g['counting_unit'])}</b></p>
<div class="bars">{''.join(bars)}</div><p class="muted">Unresolved: {residual:.1f}% · Unassigned: {unassigned:.1f}%</p>
<details><summary>Evidence and haplotype records</summary><p>Frequency basis: {esc(g['frequency_basis'])}<br>Source: {esc(g['source'])}</p>
{table(g['rows'],['id','abundance','support','confidence','resolution','span','edits'])}</details></article>''')
        ungrouped=[r for r in data['ungrouped'] if (r['sample'],r['segment'])==(sample,segment)]
        extra=''
        if ungrouped:
            extra='<details><summary>Rows without comparison groups ('+str(len(ungrouped))+')</summary><p>No population totals can be assigned to these rows.</p>'+table(ungrouped,['id','abundance','support','confidence','resolution','span','edits'])+'</details>'
        if not tiles and not ungrouped:extra='<p class="muted">Consensus only. No haplotype records were supplied.</p>'
        sections.append(f'''<section class="segment"><div class="sectionhead"><div><small>{esc(sample)}</small><h2>{esc(segment)}</h2></div><p>{e['length']:,} bases · {e['unknown_bases']:,} N bases · {e['rows']} rows</p></div><div class="groups">{''.join(tiles)}</div>{extra}</section>''')
    nrows=sum(e['rows'] for e in entries);nsamples=len({e['sample'] for e in entries})
    warning=''.join('<li>'+esc(w)+'</li>' for w in data['warnings'])
    label='SYNTHETIC DEMO · NOT RESEARCH RESULTS' if data.get('synthetic_demo') else 'SUPPLIED RECORDS · EVIDENCE REVIEW'
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Viral Cloud · Human Link GenoMix</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f3f6fc;color:#152c4d;font:15px/1.55 system-ui,Segoe UI,sans-serif}.shell{max-width:1180px;margin:auto;padding:32px 28px}header{background:#102d56;color:white}header .shell{padding-top:36px;padding-bottom:36px}.brand{font-size:12px;letter-spacing:2px;color:#a9caff}.hero{display:flex;gap:22px;align-items:center}.mark{background:#3b82f6;border-radius:18px 18px 18px 5px;font-size:46px;color:#102d56;font-weight:900;width:76px;text-align:center;position:relative}.mark:after{content:'•';position:absolute;right:9px;top:-13px;color:white;font-size:30px}h1{font-size:40px;margin:6px 0}h2{font-size:24px;margin:0}h3{font-size:18px;margin:0}header p{margin:0;color:#c5d6ed}.notice{background:#eaf2ff;border:1px solid #bfd6fa;border-radius:12px;padding:16px 20px;margin-bottom:24px}.notice strong{color:#1d4ed8}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}.metric{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:19px}.metric b{display:block;font-size:28px}.metric span{color:#60728b}.segment{margin:24px 0;background:white;border:1px solid #dbe3ef;border-radius:16px;padding:24px}.sectionhead,.grouphead{display:flex;justify-content:space-between;align-items:center;gap:16px}.sectionhead{border-bottom:1px solid #e5ebf4;padding-bottom:18px;margin-bottom:20px}.sectionhead small{color:#60728b}.sectionhead p{color:#60728b}.groups{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:20px}.group{background:#f8faff;border:1px solid #e0e8f4;padding:20px;border-radius:12px;min-width:0}.group p{font-size:13px}.pill{font-size:11px;background:#e1edff;color:#2454a1;border-radius:15px;padding:4px 9px;white-space:nowrap}.barrow{display:grid;grid-template-columns:55px 1fr 55px;gap:10px;align-items:center;margin:12px 0;font-size:13px}.barrow strong{text-align:right}.track{height:12px;background:#e1e8f4;border-radius:6px;overflow:hidden}.track i{display:block;background:#3b82f6;height:100%;border-radius:6px}.muted{color:#657791}details{border-top:1px solid #dfe7f1;margin-top:18px;padding-top:13px}summary{cursor:pointer;font-weight:600;color:#2454a1}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px;margin-top:12px}th,td{padding:9px;text-align:left;border-bottom:1px solid #dfe7f1;white-space:nowrap}th{color:#60728b;font-weight:500}footer{font-size:12px;color:#64768f;margin:25px 0}a{color:#2454a1}button{background:#fff;border:1px solid #bfd0e8;padding:8px 14px;border-radius:8px;color:#2454a1;cursor:pointer}.tools{display:flex;gap:16px;align-items:center;flex-wrap:wrap}@media(max-width:650px){.shell{padding:20px 14px}.metrics{grid-template-columns:repeat(2,1fr)}.sectionhead{display:block}.groups{grid-template-columns:1fr}.grouphead{flex-wrap:wrap}h1{font-size:31px}.segment{padding:16px}}@media print{body{background:white}.tools{display:none}details{display:block}.segment{break-inside:avoid}header{background:white;color:#102d56}header p,.brand{color:#60728b}}
</style></head><body><header><div class="shell"><div class="brand">HUMAN LINK GenoMix / VIROLOGIX</div><div class="hero"><div class="mark" aria-hidden="true">v</div><div><h1>Viral Cloud</h1><p>Haplotype evidence, at the resolution the data support.</p></div></div></div></header><main class="shell">'''+f'''
<div class="notice"><strong>{label}</strong><br>This report organizes supplied records. It does not infer haplotypes, validate linkage, or predict future variants.</div>
<div class="tools"><a href="population.cfasta">cFASTA</a><a href="consensus.fasta">Consensus FASTA</a><a href="viral-cloud.json">Report JSON</a><a href="evidence.json">Evidence metadata</a><a href="manifest.json">Checksums</a></div>
<div class="metrics"><div class="metric"><b>{nsamples}</b><span>Samples</span></div><div class="metric"><b>{len(entries)}</b><span>Segment entries</span></div><div class="metric"><b>{nrows}</b><span>Supplied haplotype rows</span></div><div class="metric"><b>{len(groups)}</b><span>Comparison groups</span></div></div>
<p class="muted">Bars show reported frequency within each declared group. Matching spans or identifiers do not establish linkage between groups. Confidence labels are supplied, not calibrated by this tool.</p>
{''.join(sections)}
<section class="segment"><h2>Interpretation & provenance</h2><ul>{warning}</ul><details><summary>Method and limitations</summary><p>Viral Cloud {esc(data['version'])} validates cFASTA structure and declared evidence consistency, preserves the consensus once per segment, and exports a separate ordinary FASTA. It does not assign an H0 sequence or normalize across independent groups. No biological conclusions are inferred. Missing metadata remains unresolved.</p><p>The legacy INFERRED resolution label is retained for compatibility; the evidence sidecar separates method from span. A reviewed future format revision is still required. Unassigned fraction is arithmetic remainder, not proof of an additional haplotype.</p><p>Input and output SHA-256 checksums are in manifest.json. Checksums support file identity, not scientific validation.</p></details></section>
<footer>Human Link GenoMix · Viral Cloud preview {esc(data['version'])} · Offline report · No external scripts, fonts or telemetry.</footer></main></body></html>'''
