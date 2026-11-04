"""Operational freshness checks with synthetic timestamps and sparse events."""
import unittest
from unittest.mock import patch,MagicMock
import pandas as pd
from data_health import sync_status,sync_health,measurement_health,GARMIN_DATASETS


class FreshnessTests(unittest.TestCase):
    now=pd.Timestamp('2025-06-10T18:00:00Z')

    def test_grace_boundary_and_timezone_offsets(self):
        log=pd.DataFrame([{'started_at':'2025-06-09T20:00:00-04:00','status':'ok'}])
        self.assertEqual(sync_status('Test',log,self.now,18)['Status'],'Recent check')
        self.assertEqual(sync_status('Test',log,self.now+pd.Timedelta(seconds=1),18)['Status'],'Check overdue')

    def test_latest_failure_and_later_recovery(self):
        log=pd.DataFrame([{'started_at':'2025-06-10T16:00:00Z','status':'ok'},
                          {'started_at':'2025-06-10T17:00:00Z','status':'error'}])
        self.assertEqual(sync_status('Test',log,self.now,18)['Status'],'Latest check failed')
        log.loc[2]=['2025-06-10T17:30:00Z','ok']
        self.assertEqual(sync_status('Test',log,self.now,18)['Status'],'Recent check')

    def test_one_failed_dataset_is_not_hidden_by_other_successes(self):
        logs=pd.DataFrame([{'source':'Garmin API','dataset':d,
            'started_at':'2025-06-10T16:00:00Z','status':'ok'} for d in GARMIN_DATASETS])
        logs.loc[logs.dataset.eq('sleep_summaries'),'status']='error'
        report=sync_health(logs,'2025-06-10T16:00:00Z',self.now)
        self.assertEqual(report.loc[report.Source.eq('Garmin · sleep summaries'),'Status'].iloc[0],
                         'Latest check failed')
        self.assertEqual(report.loc[report.Source.eq('Hevy'),'Status'].iloc[0],'Recent check')

    def test_no_records_bad_timestamp_and_future_clock_are_not_healthy(self):
        self.assertEqual(sync_status('Test',pd.DataFrame(),self.now,18)['Status'],'Not recorded')
        log=pd.DataFrame([{'started_at':'invalid','status':'ok'}])
        self.assertEqual(sync_status('Test',log,self.now,18)['Status'],'Not recorded')
        log.iloc[0]=['2025-06-11T18:00:00Z','ok']
        self.assertEqual(sync_status('Test',log,self.now,18)['Status'],'Clock mismatch')

    def test_sparse_workouts_bp_and_bodyfat_are_on_demand(self):
        old=pd.DatetimeIndex(['2025-01-01'])
        table=measurement_health(pd.DataFrame(),pd.Series(dtype=float),pd.DataFrame(),
              pd.DataFrame({'systolic':[120]},index=old),
              pd.DataFrame({'body_fat_pct':[20]},index=old),pd.DataFrame({'workout_id':['x']},index=old),
              '2025-06-10').set_index('Measurement')
        for label in ['Blood pressure','Body fat','Hevy workout']:
            self.assertEqual(table.loc[label,'Status'],'On demand')
        self.assertEqual(table.loc['Garmin sleep','Status'],'No measurements')

    def test_per_metric_freshness_completed_days_and_future_dates(self):
        dates=pd.date_range('2025-06-03',periods=8)
        daily=pd.DataFrame({'calories':2400.,'meals':4},index=dates)
        garmin=pd.DataFrame({'steps':0.,'sleep_hours':7.,'hrv_ms':50.},index=dates)
        garmin.loc[dates[-4]:,'sleep_hours']=float('nan')
        garmin.loc[pd.Timestamp('2025-07-01')]=[9000,8,50]
        t=measurement_health(daily,pd.Series(150.,index=dates),garmin,pd.DataFrame(),
                             pd.DataFrame(),pd.DataFrame(),'2025-06-10').set_index('Measurement')
        self.assertEqual(t.loc['Nutrition · logging proxy','Days measured · last 7 completed'],7)
        self.assertEqual(t.loc['Garmin steps','Days measured · last 7 completed'],7)
        self.assertEqual(t.loc['Garmin sleep','Status'],'Measurement lag')
        self.assertEqual(t.loc['Garmin HRV','Status'],'Recent measurements')

    def test_unchanged_drive_export_records_a_check_without_reimport(self):
        import sync_health_connect_drive as hc
        db=MagicMock()
        with patch.dict('os.environ',{'DATABASE_URL':'postgresql://synthetic'}),\
             patch('sys.argv',['sync_health_connect_drive.py']),\
             patch.object(hc,'latest_export',return_value=(object(),{'id':'synthetic'})),\
             patch.object(hc,'connect',return_value=db),\
             patch.object(hc,'ensure_schema'),\
             patch.object(hc,'previously_imported',return_value=True),\
             patch.object(hc,'log_import') as log,\
             patch.object(hc,'download_and_verify') as download:
            hc.main()
            log.assert_called_once_with(db,hc.SOURCE,'drive_check',0)
            download.assert_not_called()
            db.close.assert_called_once()

    def test_overview_notice_renders_with_missing_sources(self):
        from streamlit.testing.v1 import AppTest
        at=AppTest.from_string("""
import pandas as pd
from data_health import sync_health,measurement_health,render_freshness
sync=sync_health(pd.DataFrame(),None,pd.Timestamp('2025-06-10T18:00:00Z'))
measurements=measurement_health(pd.DataFrame(),pd.Series(dtype=float),pd.DataFrame(),
                               pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),'2025-06-10')
render_freshness(sync,measurements)
""").run()
        self.assertFalse(at.exception)
        self.assertTrue(at.warning)
        self.assertEqual(len(at.dataframe),2)


if __name__=='__main__':
    unittest.main()
