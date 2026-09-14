"""Read-only validation of the existing channel connection; never uploads or refreshes files."""
import argparse
import pickle
from .core import now,save
from .analytics import query_metrics

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--token',required=True);args=parser.parse_args()
    try:
        with open(args.token,'rb') as stream: creds=pickle.load(stream)
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        if not creds.valid: creds.refresh(Request())
        yt=build('youtube','v3',credentials=creds,cache_discovery=False)
        channels=yt.channels().list(part='snippet,contentDetails',mine=True).execute()['items']
        channel=next((c for c in channels if c['snippet']['title'].lower()=='hidden logic'),None)
        if channel is None: raise RuntimeError('Connected account is not Hidden Logic')
        playlist=channel['contentDetails']['relatedPlaylists']['uploads']
        items=yt.playlistItems().list(part='contentDetails',playlistId=playlist,maxResults=50).execute()['items']
        from .core import parse
        eligible=[i for i in items if 10 <= (now()-parse(i['contentDetails']['videoPublishedAt'])).days <= 30]
        if not eligible: raise RuntimeError('No mature video available for analytics probe')
        video=eligible[0]['contentDetails']['videoId']
        import datetime as dt
        end=now().date()-dt.timedelta(days=3);start=end-dt.timedelta(days=30)
        api=build('youtubeAnalytics','v2',credentials=creds,cache_discovery=False)
        report=query_metrics(api,video,start.isoformat(),end.isoformat())
        report['status']='connected';report['channel']='Hidden Logic';report['video_id']=video
        try:
            curve=api.reports().query(ids='channel==MINE',startDate=start.isoformat(),endDate=end.isoformat(),
                filters='video=='+video,dimensions='elapsedVideoTimeRatio',metrics='audienceWatchRatio',
                sort='elapsedVideoTimeRatio').execute()
            report['retention_curve_points']=len(curve.get('rows',[]))
        except Exception as exc:
            from .analytics import error_detail
            report['retention_error']=error_detail(exc)
        save('outputs/analytics-connection.json',report)
        print('Hidden Logic connection checked; report availability:', report['availability'])
    except Exception as exc:
        save('outputs/analytics-connection.json',{'status':'unavailable','error_type':type(exc).__name__})
        print('Analytics connection unavailable:',type(exc).__name__)

if __name__=='__main__':main()
