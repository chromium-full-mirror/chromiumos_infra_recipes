# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

from PB.chromite.api import packages

CHROMIUM_CACHE_DIR = '/preload/chrome_cache'


class ChromeApi(recipe_api.RecipeApi):

  def __init__(self, properties, *args, **kwargs):
    super(ChromeApi, self).__init__(*args, **kwargs)
    self._parallel_sync_jobs = 72
    if properties.parallel_sync_jobs > 0:
      self._parallel_sync_jobs = properties.parallel_sync_jobs

  def sync(self, chrome_root, chroot, build_target, internal):
    """
    Sync Chrome source code.

    Must be run with cwd inside a chromiumos source root.

    Args:
      chrome_root (str): Directory to sync the Chrome source code to.
      chroot (chromiumos.Chroot): Information on the chroot for the build.
      build_target (chromiumos.BuildTarget): Build target of the build.
      internal (bool): True for internal checkout.
    """
    with self.m.step.nest('sync chrome'):
      request = packages.GetChromeVersionRequest(
          chroot=chroot,
          build_target=build_target)
      version = self.m.cros_build_api.PackageService.GetChromeVersion(
          request, infra_step=True).version

      self.m.file.ensure_directory('ensure chrome root', chrome_root)

      # Similar to what you would get with self.m.gclient.checkout approach
      # but here we up the job parallelism for a speed boost.
      with self.m.context(cwd=chrome_root):
        cfg = self.m.gclient.make_config(CACHE_DIR=CHROMIUM_CACHE_DIR)
        soln = cfg.solutions.add()
        soln.name = 'src'
        soln.url = 'https://chromium.googlesource.com/chromium/src.git'
        soln.revision = version
        soln.custom_vars = {
            'checkout_src_internal': internal,
        }

        config_cmd = [
            'config',
            '--spec',
            self.m.gclient.config_to_pythonish(cfg),
        ]

        adjust_cmd = [
            'sed',
            '-i',
            '$ a\\target_os = ["chromeos"]',
            '.gclient',
        ]

        sync_cmd = [
            'sync',
            '--verbose',
            '--nohooks',
            '-j%d' % self._parallel_sync_jobs,
            '--reset',
            '--force',
            '--upstream',
            '--no-nag-max',
            '--with_branch_heads',
            '--with_tags',
            '--delete_unversioned_trees',
            '--revision',
            'src@%s' % version,
        ]

        with self.m.depot_tools.on_path():
          # Writes out the .gclient file.
          self.m.python('gclient config',
                        self.m.depot_tools.root.join('gclient.py'),
                        config_cmd,
                        infra_step=True)

          # Adjust .gclient to include required target_os directive.
          # This appends one line to the gclient config file.
          self.m.step('adjust gclient config', adjust_cmd)

          # Finally, start the sync.
          self.m.python('gclient sync',
                        self.m.depot_tools.root.join('gclient.py'),
                        sync_cmd,
                        infra_step=True)
