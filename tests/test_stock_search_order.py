import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import visuals


def candidate(identity, description):
    return {'id':identity, 'provider':'pexels',
            'url':'https://www.pexels.com/video/'+description.replace(' ','-')+'-123/'}


class StockSearchOrderTests(unittest.TestCase):
    def test_providers_keep_relevance_order_and_both_reach_shortlist(self):
        first=[candidate('px-'+str(i),'zipper') for i in range(15)]
        second=[{'id':'pb-'+str(i),'provider':'pixabay','slug':'zipper'} for i in range(15)]
        with patch.object(visuals,'_search_pexels',return_value=first), \
             patch.object(visuals,'_search_pixabay',return_value=second):
            clips=visuals._search_all({'pexels':'test','pixabay':'test'},'zipper')
        self.assertEqual([clip['id'] for clip in clips[:4]],['px-0','pb-0','px-1','pb-1'])
        self.assertEqual([clip['id'] for clip in clips[::2]],[clip['id'] for clip in first])

    def test_object_match_past_twelfth_result_is_not_discarded(self):
        clips=[candidate(str(i),'close up brown fabric') for i in range(12)]
        clips.append(candidate('actual-zipper','zipper pull tab'))
        with patch.object(visuals,'_search_all',return_value=clips), patch.object(visuals,'_score_candidates') as gemini:
            selected,_=visuals._search_and_score({},'test','zipper pull tab close up','','','',True,8,skip_scoring=True)
        self.assertEqual(selected[0]['id'],'actual-zipper')
        self.assertEqual(len(selected),12)
        self.assertEqual(selected[0]['assessment_status'],'unverified')
        self.assertEqual(selected[0]['score'],0)
        gemini.assert_not_called()

    def test_camera_and_action_words_do_not_outweigh_actual_object(self):
        clips=[candidate('wrong','hand holding close up slow motion'),candidate('right','zipper')]
        self.assertEqual(visuals._prioritize_candidates('zipper hand holding close up slow motion',clips)[0]['id'],'right')

    def test_missing_description_stays_eligible_and_stable_ties_keep_provider_order(self):
        clips=[candidate('first','zipper'),candidate('second','zipper'),{'id':'unknown'}]
        self.assertEqual([c['id'] for c in visuals._prioritize_candidates('zipper',clips)],['first','second','unknown'])
        self.assertEqual(visuals._prioritize_candidates('close up',clips),clips)

    def test_rejected_ids_are_removed_before_shortlist_cap(self):
        clips=[candidate(str(i),'zipper') for i in range(14)]
        with patch.object(visuals,'_search_all',return_value=clips):
            selected,_=visuals._search_and_score({},None,'zipper','','','',True,8,
                skip_scoring=True,excluded_source_ids={str(i) for i in range(12)})
        self.assertEqual([c['id'] for c in selected],['12','13'])

    def test_actual_download_uses_best_object_match_and_retains_unverified_status(self):
        clips=[candidate('brown','brown fabric'),candidate('zipper','zipper pull tab')]
        downloaded=[]
        def download(clip,path):
            downloaded.append(clip)
            Path(path).write_bytes(clip['id'].encode())
            return True
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(visuals,'_search_all',return_value=clips), \
             patch.object(visuals,'_load_used',return_value=set()), \
             patch.object(visuals,'_download',side_effect=download), \
             patch.object(visuals.time,'sleep'):
            paths=visuals.fetch_backgrounds('test',['zipper pull tab close up'],directory,count=1,
                metadata_scoring=False,record_history=False)
            self.assertEqual(Path(paths[0]).read_bytes(),b'zipper')
        self.assertEqual(downloaded[0]['assessment_status'],'unverified')


if __name__=='__main__':unittest.main()
