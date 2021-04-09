# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

# TODO(b/180715619): This module exists for prototyping purposes.
# Delete once cloudready is fully integrated into ChromeOS.

NEVERWARE_BROWSER_REPO_URL = (
    'https://chrome-internal.googlesource.com/' +
    'external/gitlab.neverware.com/neverware/chromium-browser')

# Temporary hack, see go/build-cloudready for context.
EXISTING_SKIA_SRC = 'git@gitlab.neverware.com:neverware/skia'
NEW_SKIA_SRC = 'https://chrome-internal.googlesource.com/external/gitlab.neverware.com/neverware/skia'
NEVERWARE_DEPS_FILE = 'src/tools/neverware/neverware_deps.conf'
SKIA_CMD = [
    'sed', '-i', "'s#{}#{}#g'".format(EXISTING_SKIA_SRC, NEW_SKIA_SRC),
    NEVERWARE_DEPS_FILE
]


class CloudreadyApi(recipe_api.RecipeApi):

  def setup_cloudready_workspace(self):
    """Perform additional Cloudready-specific workspace instructions.

    Assumes that the current working directory is the workspace root.
    """
    # TODO(b/180715619): Much of this is hard-coded to speed up prototyping.
    # Generalize before productionizing.
    with self.m.step.nest("cloudready specific setup"):
      browser_dir = self.m.cros_source.workspace_path.join('src/browser')
      self.m.file.ensure_directory('create src/browser', browser_dir)

      with self.m.context(cwd=browser_dir):
        self.m.step('download cloudready .gclient file', [
            'wget',
            'https://s3.amazonaws.com/neverware-dev/.gclient',
        ])

        browser_src_dir = browser_dir.join('src')
        self.m.file.ensure_directory('create src dir', browser_src_dir)
        with self.m.context(cwd=browser_src_dir,
                            env={'GIT_HTTP_LOW_SPEED_LIMIT': '0'}):
          self.m.git.clone(NEVERWARE_BROWSER_REPO_URL,
                           branch='upstream/neverware-d90', verbose=True,
                           progress=True)

        # Temporary hack, see go/build-cloudready for context.
        self.m.step('update deps file', SKIA_CMD)

        self.m.step('gclient sync', ['gclient', 'sync'])
