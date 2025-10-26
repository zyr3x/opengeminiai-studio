import os
import tempfile
import unittest
from app.utils.core.file_processing_utils import process_message_for_paths

class TestFileProcessingUtils(unittest.TestCase):

    def setUp(self):
        # Create a temporary file for testing
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        self.temp_file.write(b"test content")
        self.temp_file.close()
        self.temp_file_path = self.temp_file.name

    def tearDown(self):
        # Clean up the temporary file
        os.remove(self.temp_file_path)

    def test_duplicate_path_processing(self):
        """
        Tests that the same file path, referenced multiple times, is only processed once.
        """
        # Using a real path and a relative path that point to the same file.
        relative_path = os.path.basename(self.temp_file_path)
        with open(relative_path, "w") as f:
            f.write("test content")

        content = f"Check this code: code_path={self.temp_file_path} and also this image: image_path={self.temp_file_path}"
        print(content)
        # We expect one part for "Check this code: ", one for the code content, and one for " and also this image: ".
        # The second path should be ignored.
        result, _ = process_message_for_paths(content)

        # Clean up relative path file
        os.remove(relative_path)

        self.assertIsInstance(result, list)

        # Expected parts:
        # 1. Text: "Check this code: "
        # 2. Text: Code content from the file
        # 3. Text: " and also this image: "
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['text'], "Check this code: ")
        self.assertTrue(result[1]['text'].startswith("📝 **CODE CONTEXT LOADED**"))
        self.assertEqual(result[2]['text'], " and also this image: ")

    def test_duplicate_code_path_processing(self):
        """
        Tests that the same code file path, referenced multiple times, is only processed once.
        """
        content = f"code_path={self.temp_file_path} and again code_path={self.temp_file_path}"

        result, _ = process_message_for_paths(content)

        self.assertIsInstance(result, list)
        # Expected parts:
        # 1. Code content from the file
        # 2. Text: " and again "
        self.assertEqual(len(result), 2)
        self.assertTrue(result[0]['text'].startswith("📝 **CODE CONTEXT LOADED**"))
        self.assertEqual(result[1]['text'], " and again ")


if __name__ == '__main__':
    unittest.main()
