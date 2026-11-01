import copy
import json
from pathlib import Path
import tempfile
import unittest
from viralcloud.pipeline import assemble, summarize, serialize, read_fasta, write_outputs, digest
from viralcloud.cfasta import parse
from viralcloud.report import render

import viralcloud
ROOT=Path(viralcloud.__file__).parent
class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.entries=assemble((ROOT/'examples/consensus.fasta').read_text(),(ROOT/'examples/haplotypes.tsv').read_text(),'DEMO')
        self.evidence=json.loads((ROOT/'examples/evidence.json').read_text())
    def test_roundtrip(self):
        self.assertEqual(parse(serialize(self.entries)),self.entries)
    def test_independent_groups_not_pooled(self):
        s=summarize(self.entries,self.evidence)
        self.assertAlmostEqual(s['groups'][0]['reported_abundance'],.9)
        self.assertAlmostEqual(s['groups'][1]['reported_abundance'],1)
        self.assertNotIn('total_abundance',s)
    def test_no_invented_consensus_haplotype(self):
        self.assertEqual(self.entries[1].haplotypes,[])
    def test_missing_evidence_is_explicit(self):
        s=summarize(self.entries)
        self.assertEqual(len(s['ungrouped']),4)
        self.assertEqual(s['groups'],[])
    def test_bad_fasta(self):
        for text in ('>\nACGT','>A\nACGT\n>A\nACGT','>A\nacgt'):
            with self.subTest(text=text),self.assertRaises(ValueError): read_fasta(text)
    def test_invalid_denominator(self):
        for d in (0,-1,True,1.5):
            e=copy.deepcopy(self.evidence);e['groups'][0]['denominator']=d
            with self.subTest(d=d),self.assertRaises(ValueError): summarize(self.entries,e)
    def test_support_fraction_mismatch(self):
        self.evidence['groups'][0]['denominator']=201
        with self.assertRaises(ValueError): summarize(self.entries,self.evidence)
    def test_unknown_member(self):
        self.evidence['groups'][0]['members'].append('MISSING')
        with self.assertRaises(ValueError): summarize(self.entries,self.evidence)
    def test_duplicate_group(self):
        self.evidence['groups'].append(copy.deepcopy(self.evidence['groups'][0]))
        with self.assertRaises(ValueError): summarize(self.entries,self.evidence)
    def test_invalid_unresolved_mass(self):
        for v in (float('nan'),.2,-.1):
            e=copy.deepcopy(self.evidence);e['groups'][0]['unresolved_abundance']=v
            with self.subTest(v=v),self.assertRaises(ValueError): summarize(self.entries,e)
    def test_report_escapes_source(self):
        self.evidence['groups'][0]['source']='<script>alert(1)</script>'
        html=render(summarize(self.entries,self.evidence))
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;',html)
    def test_output_checksums_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'result'
            write_outputs(self.entries,self.evidence,out,{},True)
            manifest=json.loads((out/'manifest.json').read_text())
            for name,sha in manifest['outputs'].items():
                self.assertEqual(digest((out/name).read_bytes()),sha)
            self.assertIn('SYNTHETIC', (out/'viral-cloud.html').read_text())
            with self.assertRaises(FileExistsError): write_outputs(self.entries,self.evidence,out,{})
if __name__=='__main__': unittest.main()
