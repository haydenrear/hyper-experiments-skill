We have tools with an experiment runner - we have the environment set up in a standardized way. So now we can build a hyper-experiments-cli or MCP server that submits an experiment to a queue. Then, this queue can estimate will effectively be a scheduler of the ML programs.

The CLI will also be able to be queries for how close to completion it is. Then it can swap out backends. Basically we just need a central point here for scheduling. It can just be another AI but it's important to have it.

This can also do cost estimation, ping for refills, etc.

One thing we could do is deploy agent in a sandbox with GPU to also poll the experiment, cancel it, provide reports, etc.
