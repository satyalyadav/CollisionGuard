import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import parallact_v1_pilot as pilot
import parallact_collect as collect


class V1PilotTests(unittest.TestCase):
    def test_scenario_presence_only(self):
        self.assertTrue(pilot.available({'runs':{pilot.CFG:{'parallel_unaware':{'s':0}}}}))
        self.assertFalse(pilot.available({'runs':{pilot.CFG:{'other':{}}}}))
        self.assertFalse(pilot.available({'runs':{pilot.CFG:{'parallel_unaware':None}}}))

    def test_selection_exclusions_cap_and_determinism(self):
        paths=[]
        for origin in ('generated','seeds'):
            for family in ('complementary','contradictory'):
                for n in range(15):
                    paths.append(f'dataset/v1/{origin}/{family}/instance_org__repo{n}-' + f'{n:040x}' + '.json')
        excluded={paths[0],paths[20]}
        selected,shortages=pilot.select(paths,excluded)
        self.assertEqual((selected,shortages),pilot.select(reversed(paths),excluded))
        self.assertEqual(len(selected),12); self.assertFalse(shortages); self.assertFalse(set(selected)&excluded)
        counts={}
        for p in selected:
            repo=pilot.prior.parse_path(p)['repo']; counts[repo]=counts.get(repo,0)+1
        self.assertLessEqual(max(counts.values()),2)

    def test_whitespace_extra_and_private_features(self):
        path='dataset/v1/seeds/complementary/instance_org__repo-'+'a'*40+'.json'
        seed={'instance_id':Path(path).stem,'repo':'org/repo','base_commit':'b'*40,'agentA_problem_statement':'first\n\n','agentB_problem_statement':'second','agentA_solution':'ref1','agentB_solution':'ref2','family':'secret'}
        run={'cfg':pilot.CFG,'v':'v1','fam':'complementary','iid':seed['instance_id'],'scen':'parallel_unaware','messages':[],'turns':[{'agent':'A','prompt':'prefix first'},{'agent':'B','prompt':'prefix second'}],'outputs':{'A':'a','B':'b'}}
        checks,prompts,_=collect.association(seed,run,path,'prefix ')
        self.assertTrue(checks['A_assignment']); self.assertEqual(set(collect.safe_feature(seed,prompts)),{'instance_id','repo','base_commit','task_a','task_b'})
        for bad in ('prefix first extra','prefix first first'):
            run['turns'][0]['prompt']=bad; self.assertFalse(collect.association(seed,run,path,'prefix ')[0]['A_assignment'])

    def test_identity_drift(self):
        with self.assertRaises(pilot.Integrity): pilot.verify_identity({'changed':'hash'})

    def test_limits_and_error_bodies(self):
        with tempfile.TemporaryDirectory() as d:
            f=pilot.Fetcher(Path(d))
            error=urllib.error.HTTPError('https://example.test/x',404,'missing',{},io.BytesIO(b'failure'))
            with patch.object(pilot.urllib.request,'urlopen',side_effect=error):
                with self.assertRaises(pilot.Access): f.fetch('https://example.test/x','x')
            self.assertEqual(f.state['charged_bytes'],7)
            with self.assertRaises(pilot.Access): f.fetch('https://example.test/x','x')
            self.assertEqual(f.state['charged_bytes'],7)
            with patch.object(pilot.urllib.request,'urlopen',return_value=io.BytesIO(b'123456')):
                with self.assertRaises(pilot.Access): f.fetch('https://example.test/y','x',5)
            self.assertEqual(f.state['charged_bytes'],12)


if __name__=='__main__': unittest.main()
