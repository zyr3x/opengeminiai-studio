package com.opengeminiai.studio.client

import com.intellij.openapi.util.IconLoader
import com.intellij.util.ui.UIUtil
import javax.swing.Icon

object Icons {
    private val LogoLight = IconLoader.getIcon("/icons/logo-light.svg", javaClass)
    val LogoBig = IconLoader.getIcon("/icons/logo.svg", javaClass)
    val LogoDark = IconLoader.getIcon("/icons/logo-dark.svg", javaClass)

    val Logo: Icon
        get() = if (UIUtil.isUnderDarcula()) LogoDark else LogoLight
}