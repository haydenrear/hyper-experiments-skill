Agents always run rm -rf .venv --- after regression check. But this is unnecessary why?

And also after HV_SMOKE -> both of these should just clean after. We should have a function clean that cleans - and run it after - cleaning everything up so that the model doesn't have to - check all the scripts to see if it tells it to do that.
