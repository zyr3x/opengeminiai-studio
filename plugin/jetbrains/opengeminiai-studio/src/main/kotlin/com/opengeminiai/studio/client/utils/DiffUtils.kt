package com.opengeminiai.studio.client.utils
import com.intellij.diff.*
import com.intellij.diff.requests.SimpleDiffRequest
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.vfs.LocalFileSystem
import java.io.File

object DiffUtils {
    fun showDiff(project: Project, path: String, newContent: String) {
        ApplicationManager.getApplication().invokeLater {
            val vFile = LocalFileSystem.getInstance().findFileByPath(path)
            val f = DiffContentFactory.getInstance()
            val c1 = if (vFile != null) f.create(project, vFile) else f.create("")
            val c2 = f.create(newContent)

            val req = SimpleDiffRequest("Review Changes: $path", c1, c2, "Current Disk", "AI Proposed")
            DiffManager.getInstance().showDiff(project, req)
        }
    }

    fun applyChangeDirectly(project: Project, path: String, content: String) {
        ApplicationManager.getApplication().invokeLater {
            WriteCommandAction.runWriteCommandAction(project) {
                try {
                    var file = LocalFileSystem.getInstance().findFileByPath(path)
                    if (file == null) {
                        val ioFile = File(path)
                        ioFile.parentFile?.mkdirs()
                        ioFile.createNewFile()
                        file = LocalFileSystem.getInstance().refreshAndFindFileByIoFile(ioFile)
                    }
                    file?.setBinaryContent(content.toByteArray())
                } catch (e: Exception) {
                    Messages.showErrorDialog(project, "Failed to write $path: ${e.message}", "Error")
                }
            }
        }
    }
}