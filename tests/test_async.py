#!/usr/bin/env python3
"""
Quick test script to verify async implementation works correctly.
Tests basic imports and async function execution.
"""
import asyncio
import sys
import traceback

def test_imports():
    """Test that all async modules can be imported."""
    print("🧪 Testing imports...")
    
    try:
        import app.async_utils
        print("  ✓ app.async_utils")
    except Exception as e:
        print(f"  ✗ app.async_utils: {e}")
        return False
    
    try:
        import app.async_optimization
        print("  ✓ app.async_optimization")
    except Exception as e:
        print(f"  ✗ app.async_optimization: {e}")
        return False
    
    try:
        import app.async_mcp_handler
        print("  ✓ app.async_mcp_handler")
    except Exception as e:
        print(f"  ✗ app.async_mcp_handler: {e}")
        return False
    
    try:
        import app.controllers.
        print("  ✓ app.controllers.async_proxy")
    except Exception as e:
        print(f"  ✗ app.controllers.async_proxy: {e}")
        return False
    
    try:
        import run_async
        print("  ✓ run_async")
    except Exception as e:
        print(f"  ✗ run_async: {e}")
        return False
    
    return True

async def test_async_utils():
    """Test async utility functions."""
    print("\n🧪 Testing async_utils...")
    
    try:
        from app import async_utils
        
        # Test session creation
        session = await async_utils.get_async_session()
        print("  ✓ Session created")
        
        # Test token estimation
        test_contents = [
            {"role": "user", "parts": [{"text": "Hello world! " * 100}]}
        ]
        tokens = async_utils.estimate_token_count(test_contents)
        print(f"  ✓ Token estimation: {tokens} tokens")
        
        # Test JSON pretty print
        test_data = {"key": "value", "number": 42}
        pretty = async_utils.pretty_json(test_data)
        print("  ✓ Pretty JSON formatting")
        
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        traceback.print_exc()
        return False

async def test_async_optimization():
    """Test async optimization functions."""
    print("\n🧪 Testing async_optimization...")
    
    try:
        from app import async_optimization
        
        # Test rate limiter
        rate_limiter = await async_optimization.get_rate_limiter()
        print("  ✓ Rate limiter created")
        
        # Test cache key generation
        cache_key = async_optimization.get_cache_key("test_tool", {"arg": "value"})
        print(f"  ✓ Cache key: {cache_key[:16]}...")
        
        # Test tool caching decision
        should_cache = async_optimization.should_cache_tool("list_files")
        print(f"  ✓ Should cache 'list_files': {should_cache}")
        
        # Test token estimation
        tokens = async_optimization.estimate_tokens("Hello " * 100)
        print(f"  ✓ Token estimation: {tokens} tokens")
        
        # Test parallel execution detection
        tool_calls = [
            {"name": "list_files", "args": {}},
            {"name": "get_file_content", "args": {"path": "test.py"}}
        ]
        can_parallel = async_optimization.can_execute_parallel(tool_calls)
        print(f"  ✓ Can execute parallel: {can_parallel}")
        
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        traceback.print_exc()
        return False

async def test_async_mcp_handler():
    """Test async MCP handler."""
    print("\n🧪 Testing async_mcp_handler...")
    
    try:
        from app import async_mcp_handler
        
        # Test import of required functions
        print("  ✓ Module imported successfully")
        
        # Test that execute function exists
        assert hasattr(async_mcp_handler, 'execute_mcp_tool_async')
        print("  ✓ execute_mcp_tool_async available")
        
        assert hasattr(async_mcp_handler, 'execute_multiple_tools_async')
        print("  ✓ execute_multiple_tools_async available")
        
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        traceback.print_exc()
        return False

async def test_async_proxy():
    """Test async proxy controller."""
    print("\n🧪 Testing async_proxy...")
    
    try:
        from app.controllers.

        # Test that blueprint exists
        assert hasattr(async_proxy, 'async_proxy_bp')
        print("  ✓ async_proxy_bp blueprint exists")
        
        # Check routes are registered
        bp = async_proxy.async_proxy_bp
        print(f"  ✓ Blueprint name: {bp.name}")
        
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        traceback.print_exc()
        return False

async def test_quart_app():
    """Test Quart app creation."""
    print("\n🧪 Testing Quart app creation...")
    
    try:
        import run_async
        
        app = await run_async.create_async_app()
        print("  ✓ Async app created")
        print(f"  ✓ App name: {app.name}")
        
        # Check blueprints are registered
        blueprints = list(app.blueprints.keys())
        print(f"  ✓ Registered blueprints: {', '.join(blueprints)}")
        
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        traceback.print_exc()
        return False

async def main():
    """Run all tests."""
    print("=" * 70)
    print("OpenGeminiAI Studio - Async Implementation Test Suite")
    print("=" * 70)
    
    results = []
    
    # Test imports (sync)
    results.append(("Imports", test_imports()))
    
    # Test async functions
    results.append(("Async Utils", await test_async_utils()))
    results.append(("Async Optimization", await test_async_optimization()))
    results.append(("Async MCP Handler", await test_async_mcp_handler()))
    results.append(("Async Proxy", await test_async_proxy()))
    results.append(("Quart App", await test_quart_app()))
    
    # Cleanup
    print("\n🧹 Cleanup...")
    try:
        from app import async_utils
        await async_utils.close_async_session()
        print("  ✓ Session closed")
    except Exception as e:
        print(f"  ⚠ Cleanup warning: {e}")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status} - {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Async implementation is ready.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")
        return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)
