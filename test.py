import asyncio, sys
sys.path.insert(0, '.')
from config import cfg
cfg.reload()
from automation.job_scraper import JobScraper

async def test():
    scraper = JobScraper()
    jobs = await scraper.search_jobs(
        'Python Developer', 'Delhi', ['linkedin'], 3
    )
    print('Total:', len(jobs))
    for j in jobs:
        print('Title:', j['title'])
        print('Company:', j['company'])  
        print('URL:', j['url'])
        print()

asyncio.run(test())