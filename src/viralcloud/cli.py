import argparse
import json
from pathlib import Path
from .cfasta import parse
from .pipeline import assemble, summarize, write_outputs, digest
from . import __version__

def main(argv=None):
    parser=argparse.ArgumentParser(description='Package supplied consensus/haplotype records and create an offline Viral Cloud report. No raw-read processing.')
    parser.add_argument('--version',action='version',version=__version__)
    commands=parser.add_subparsers(dest='command',required=True)
    build=commands.add_parser('package',help='Create cFASTA from an existing consensus and reviewed haplotype TSV')
    build.add_argument('--consensus',required=True,type=Path)
    build.add_argument('--haplotypes',required=True,type=Path)
    build.add_argument('--sample',required=True)
    report=commands.add_parser('report',help='Report existing cFASTA records')
    report.add_argument('--input',required=True,type=Path)
    validate=commands.add_parser('validate',help='Check structure and optional evidence consistency')
    validate.add_argument('--input',required=True,type=Path)
    for sub in (build,report,validate): sub.add_argument('--evidence',type=Path)
    for sub in (build,report):
        sub.add_argument('--outdir',required=True,type=Path)
        sub.add_argument('--synthetic-demo',action='store_true')
    args=parser.parse_args(argv)
    try:
        inputs={}
        def read(path, role):
            raw=path.read_bytes();inputs[role]={"filename":path.name,"sha256":digest(raw)};return raw.decode('utf-8-sig')
        evidence=json.loads(read(args.evidence,"evidence")) if args.evidence else None
        if args.command=='package': entries=assemble(read(args.consensus,"consensus"),read(args.haplotypes,"haplotypes"),args.sample)
        else: entries=parse(read(args.input,"cfasta"))
        if args.command=='validate':
            data=summarize(entries,evidence)
            print(f'Structure valid: {len(entries)} entries; {len(data["groups"])} declared groups. Biological interpretation not validated.')
        else:
            write_outputs(entries,evidence,args.outdir,inputs,args.synthetic_demo)
            print(args.outdir/'viral-cloud.html')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        parser.exit(2,f'Viral Cloud: {exc}\n')
if __name__=='__main__': main()
