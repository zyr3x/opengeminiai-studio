#!/usr/bin/env python3
"""
Performance comparison script between sync and async modes.
Tests the proxy with concurrent requests to measure improvements.
"""
import asyncio
import aiohttp
import requests
import time
import statistics
from typing import List, Dict

# Configuration
BASE_URL = "http://localhost:8080"
API_ENDPOINT = f"{BASE_URL}/v1/chat/completions"
TEST_REQUESTS = 10
CONCURRENCY_LEVELS = [1, 5, 10]

TEST_PAYLOAD = {
    "model": "gemini-2.0-flash",
    "messages": [
        {
            "role": "user",
            "content": "Write a short poem about async programming in exactly 4 lines."
        }
    ],
    "stream": False
}

def sync_request() -> float:
    """Makes a synchronous request and returns latency in seconds."""
    start = time.time()
    try:
        response = requests.post(API_ENDPOINT, json=TEST_PAYLOAD, timeout=30)
        response.raise_for_status()
        latency = time.time() - start
        return latency
    except Exception as e:
        print(f"Error in sync request: {e}")
        return -1

async def async_request(session: aiohttp.ClientSession) -> float:
    """Makes an asynchronous request and returns latency in seconds."""
    start = time.time()
    try:
        async with session.post(API_ENDPOINT, json=TEST_PAYLOAD, timeout=30) as response:
            response.raise_for_status()
            await response.json()
            latency = time.time() - start
            return latency
    except Exception as e:
        print(f"Error in async request: {e}")
        return -1

def run_sync_test(num_requests: int) -> Dict:
    """Runs synchronous test with sequential requests."""
    print(f"\n🔄 Running {num_requests} sync requests sequentially...")
    latencies = []
    
    start = time.time()
    for i in range(num_requests):
        latency = sync_request()
        if latency > 0:
            latencies.append(latency)
        print(f"  Request {i+1}/{num_requests}: {latency:.2f}s")
    
    total_time = time.time() - start
    
    if not latencies:
        return {"error": "All requests failed"}
    
    return {
        "total_time": total_time,
        "avg_latency": statistics.mean(latencies),
        "median_latency": statistics.median(latencies),
        "min_latency": min(latencies),
        "max_latency": max(latencies),
        "requests_per_second": num_requests / total_time,
        "successful_requests": len(latencies)
    }

async def run_async_test(num_requests: int, concurrency: int) -> Dict:
    """Runs asynchronous test with concurrent requests."""
    print(f"\n⚡ Running {num_requests} async requests with concurrency={concurrency}...")
    latencies = []
    
    async with aiohttp.ClientSession() as session:
        start = time.time()
        
        # Create batches based on concurrency level
        tasks = []
        for i in range(num_requests):
            task = async_request(session)
            tasks.append(task)
            
            # Wait for batch if we hit concurrency limit
            if len(tasks) >= concurrency or i == num_requests - 1:
                batch_results = await asyncio.gather(*tasks)
                for idx, latency in enumerate(batch_results):
                    if latency > 0:
                        latencies.append(latency)
                        print(f"  Request {i-len(tasks)+idx+2}/{num_requests}: {latency:.2f}s")
                tasks = []
        
        total_time = time.time() - start
    
    if not latencies:
        return {"error": "All requests failed"}
    
    return {
        "total_time": total_time,
        "avg_latency": statistics.mean(latencies),
        "median_latency": statistics.median(latencies),
        "min_latency": min(latencies),
        "max_latency": max(latencies),
        "requests_per_second": num_requests / total_time,
        "successful_requests": len(latencies)
    }

def print_comparison(sync_results: Dict, async_results: Dict, test_name: str):
    """Prints a comparison table."""
    print(f"\n{'='*70}")
    print(f"📊 {test_name}")
    print(f"{'='*70}")
    
    if "error" in sync_results or "error" in async_results:
        print("❌ Test failed - check if server is running")
        return
    
    print(f"\n{'Metric':<25} {'Sync':<20} {'Async':<20} {'Speedup':<10}")
    print(f"{'-'*75}")
    
    metrics = [
        ("Total Time", "total_time", "s"),
        ("Avg Latency", "avg_latency", "s"),
        ("Median Latency", "median_latency", "s"),
        ("Min Latency", "min_latency", "s"),
        ("Max Latency", "max_latency", "s"),
        ("Requests/sec", "requests_per_second", "req/s"),
    ]
    
    for label, key, unit in metrics:
        sync_val = sync_results[key]
        async_val = async_results[key]
        
        if key == "requests_per_second":
            speedup = async_val / sync_val if sync_val > 0 else 0
        else:
            speedup = sync_val / async_val if async_val > 0 else 0
        
        sync_str = f"{sync_val:.2f} {unit}"
        async_str = f"{async_val:.2f} {unit}"
        speedup_str = f"{speedup:.2f}x"
        
        # Color code speedup
        if speedup > 1.5:
            speedup_str = f"🚀 {speedup_str}"
        elif speedup > 1.1:
            speedup_str = f"✓ {speedup_str}"
        
        print(f"{label:<25} {sync_str:<20} {async_str:<20} {speedup_str:<10}")
    
    print(f"\n{'='*70}\n")

async def main():
    """Main benchmark runner."""
    print("🧪 OpenGeminiAI Studio - Async Performance Benchmark")
    print("=" * 70)
    print(f"Target: {BASE_URL}")
    print(f"Endpoint: {API_ENDPOINT}")
    print(f"Test requests per run: {TEST_REQUESTS}")
    print(f"Concurrency levels: {CONCURRENCY_LEVELS}")
    print("\nMake sure the server is running before starting tests!")
    
    input("\nPress Enter to start benchmarking...")
    
    # Test 1: Sequential (concurrency=1)
    print("\n" + "="*70)
    print("TEST 1: Sequential Requests (Concurrency = 1)")
    print("="*70)
    
    sync_seq = run_sync_test(TEST_REQUESTS)
    await asyncio.sleep(2)  # Cool down
    async_seq = await run_async_test(TEST_REQUESTS, concurrency=1)
    
    print_comparison(sync_seq, async_seq, "Test 1: Sequential (1 request at a time)")
    
    # Test 2: Low Concurrency
    print("\n" + "="*70)
    print("TEST 2: Low Concurrency (5 concurrent requests)")
    print("="*70)
    
    # Note: Sync mode doesn't benefit from concurrency in this test
    # In real scenario, you'd need threads/multiprocessing
    await asyncio.sleep(2)
    async_low = await run_async_test(TEST_REQUESTS, concurrency=5)
    
    print(f"\n⚡ Async (concurrency=5):")
    print(f"  Total time: {async_low['total_time']:.2f}s")
    print(f"  Requests/sec: {async_low['requests_per_second']:.2f}")
    print(f"  Avg latency: {async_low['avg_latency']:.2f}s")
    
    # Test 3: High Concurrency
    print("\n" + "="*70)
    print("TEST 3: High Concurrency (10 concurrent requests)")
    print("="*70)
    
    await asyncio.sleep(2)
    async_high = await run_async_test(TEST_REQUESTS, concurrency=10)
    
    print(f"\n⚡ Async (concurrency=10):")
    print(f"  Total time: {async_high['total_time']:.2f}s")
    print(f"  Requests/sec: {async_high['requests_per_second']:.2f}")
    print(f"  Avg latency: {async_high['avg_latency']:.2f}s")
    
    # Summary
    print("\n" + "="*70)
    print("📈 SUMMARY")
    print("="*70)
    
    if "error" not in sync_seq and "error" not in async_seq:
        seq_speedup = async_seq['requests_per_second'] / sync_seq['requests_per_second']
        print(f"\n✓ Sequential: Async is {seq_speedup:.2f}x faster")
    
    if "error" not in async_seq and "error" not in async_low:
        low_speedup = async_low['requests_per_second'] / async_seq['requests_per_second']
        print(f"✓ Low concurrency: {low_speedup:.2f}x throughput improvement")
    
    if "error" not in async_seq and "error" not in async_high:
        high_speedup = async_high['requests_per_second'] / async_seq['requests_per_second']
        print(f"✓ High concurrency: {high_speedup:.2f}x throughput improvement")
    
    print("\n" + "="*70)
    print("🎉 Benchmark complete!")
    print("="*70)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Benchmark interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error running benchmark: {e}")
        import traceback
        traceback.print_exc()
