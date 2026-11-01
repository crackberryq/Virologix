"""Pipeline capability boundary; FluPop declares no follow-up workflow."""
def available(run,store=None):return False
def source_options(store,run):return []
def create_followup(*args,**kwargs):raise ValueError('This pipeline does not declare a follow-up workflow.')
