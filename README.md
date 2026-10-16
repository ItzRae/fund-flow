# FundFlow

I'm building FundFlow to learn how to take financial report data from a web page and turn it into records I can validate and store. 
The starting point is a small local portal with made-up fund data. From there, I plan to write a Python Playwright collector, preserve the raw data in S3, and store validated records in MongoDB.

## Run locally

From the project directory, run:

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory portal
```

Open http://127.0.0.1:8000. Stop the server with `Ctrl+C`.

## Progress

The local portal displays two sample metrics for one fund after a one-second delay. This gives the Playwright collector a page where it will need to wait for report data to appear before reading it.

Collection, validation, and storage are still to come. All report data is synthetic.
