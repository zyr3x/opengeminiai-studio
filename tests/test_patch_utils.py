import os
import unittest
import shutil
from app.utils.core import patch_utils

class TestPatchUtils(unittest.TestCase):
    def setUp(self):
        self.test_dir = "tests/temp_patch_test"
        os.makedirs(self.test_dir, exist_ok=True)
        self.target_file = os.path.join(self.test_dir, "target.py")
        with open(self.target_file, "w") as f:
            f.write("def hello():\n    print('Hello World')\n")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_apply_patch(self):
        response_text = f"""
Here is the fix:

File: `{self.target_file}`
<<<<<<< SEARCH
def hello():
    print('Hello World')
=======
def hello():
    print('Hello Universe')
>>>>>>> REPLACE

Hope this helps!
"""
        cleaned_text, changes = patch_utils.apply_patches(response_text)
        
        # Verify file content
        with open(self.target_file, "r") as f:
            content = f.read()
            self.assertEqual(content, "def hello():\n    print('Hello Universe')\n")
            
        # Verify cleaned text
        self.assertIn("[Patch applied to target.py]", cleaned_text)
        self.assertNotIn("<<<<<<< SEARCH", cleaned_text)
        self.assertIn("Hope this helps!", cleaned_text)
        self.assertTrue(len(changes) > 0)

if __name__ == "__main__":
    unittest.main()
