# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

from recipe_engine import recipe_api

from PB.chromite.api import packages
from PB.chromite.api.packages import BuildsChromeRequest
from PB.chromite.api.packages import HasChromePrebuiltRequest

CHROMIUM_CACHE_DIR = '/preload/chrome_cache'

# The following project->regexes should trigger a chrome rebuild.
CHROMIUM_REBUILD_REGEXES = {
  'chromiumos/overlays/chromiumos-overlay':
    [re.compile('chromeos-base/chromeos-chrome/'
                'chromeos-chrome-.+?\.ebuild$')],
}

class ChromeApi(recipe_api.RecipeApi):

  def __init__(self, properties, *args, **kwargs):
    super(ChromeApi, self).__init__(*args, **kwargs)
    self._parallel_sync_jobs = 72
    if properties.parallel_sync_jobs > 0:
      self._parallel_sync_jobs = properties.parallel_sync_jobs
    self._deps_isolate = (properties.deps_isolate
                          if properties.HasField('deps_isolate')
                          else None)
    self._version = properties.version

  def sync(self, chrome_root, chroot, build_target, internal):
    """
    Sync Chrome source code.

    Must be run with cwd inside a chromiumos source root.

    Args:
      chrome_root (Path): Directory to sync the Chrome source code to.
      chroot (chromiumos.Chroot): Information on the chroot for the build.
      build_target (chromiumos.BuildTarget): Build target of the build.
      internal (bool): True for internal checkout.
    """
    with self.m.step.nest('sync chrome') as pres:
      if self._version or self._deps_isolate:
        version = self._version
      else:
        request = packages.GetChromeVersionRequest(
            chroot=chroot,
            build_target=build_target)
        version = self.m.cros_build_api.PackageService.GetChromeVersion(
            request, infra_step=True).version

      self.m.file.ensure_directory('ensure chrome root', chrome_root)

      if self._deps_isolate:
        di = self._deps_isolate
        self.m.isolated.download('download DEPS from isolate',
                                 isolated_hash=di.isolated_hash,
                                 isolate_server=di.isolate_server,
                                 output_dir=chrome_root)

      # Similar to what you would get with self.m.gclient.checkout approach
      # but here we up the job parallelism for a speed boost.
      with self.m.context(cwd=chrome_root):
        cfg = self.m.gclient.make_config(CACHE_DIR=CHROMIUM_CACHE_DIR)
        cfg.target_os = ['chromeos']
        soln = cfg.solutions.add()
        soln.name = 'src'
        soln.url = 'https://chromium.googlesource.com/chromium/src.git'
        soln.custom_vars = {
            'checkout_src_internal': internal,
        }
        if self._deps_isolate:
          soln.deps_file = str(chrome_root) + '/DEPS'
        if version:
          soln.revision = version

        config_cmd = [
            'config',
            '--spec',
            self.m.gclient.config_to_pythonish(cfg),
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
        ]

        if version:
          sync_cmd.extend(['--revision', 'src@%s' % version])

        with self.m.depot_tools.on_path():
          # Writes out the .gclient file.
          self.m.python('gclient config',
                        self.m.depot_tools.root.join('gclient.py'),
                        config_cmd,
                        infra_step=True)

          # Reads what we just wrote for user consumption.
          gclient_text = (
              self.m.file.read_text('gclient contents',
                                    chrome_root.join('.gclient'),
                                    test_data='solutions = [ {"name":"src"}]'))
          pres.logs['gclient configuration'] = gclient_text.splitlines()

          # Finally, start the sync.
          self.m.python('gclient sync',
                        self.m.depot_tools.root.join('gclient.py'), sync_cmd,
                        infra_step=True, timeout=60 * 60)

  def diffed_files_requires_rebuild(self, patch_sets=None):
    """Returns a bool if patch_sets includes files that require rebuilding.

    The patch_sets object supplied must have been constructed with the file
    information populated.

    Args:
      patch_sets (List[gerrit.PatchSet]): List of patch sets (with FileInfo).

    Returns:
      A bool that indicates a rebuild should be triggered.
    """
    patch_sets = patch_sets or []

    with self.m.step.nest('check if diff requires chrome rebuild') as pres:
      for patch_set in patch_sets:
        if patch_set.project in CHROMIUM_REBUILD_REGEXES:
          regex_list = CHROMIUM_REBUILD_REGEXES[patch_set.project]
          for f_path in patch_set.file_infos.keys():
            for regex in regex_list:
              if regex.match(f_path):
                pres.step_text = '%s caused chrome build' % f_path
                return True
      pres.step_text = 'no file diffs caused rebuild'
    return False

  def builds_chrome_from_source(self, build_target, chroot, packages=None,
                                internal=False, ignore_prebuilts=False):
    """Returns whether this run should build Chrome from source.

    Args:
      build_target (chromiumos.BuildTarget): Build target of the build.
      chroot (chromiumos.Chroot): Information on the chroot for the build.
      packages (list[chromiumos.PackageInfo]): Packages that the builder needs
          to build, or empty / None for default packages.
      internal (bool): Check for the internal version of chrome.
      ignore_prebuilts (bool): Whether to ignore prebuilts.  Setting this to
          true will cause Chrome to be built from source, rather than use a
          prebuilt.

    Returns:
      bool: Whether or not this run needs to build Chrome from source.
    """
    if not self.needs_chrome(build_target, chroot, packages):
      return False
    else:
      return not self.has_chrome_prebuilt(build_target, chroot,
                                          internal=internal,
                                          ignore_prebuilts=ignore_prebuilts)

  def has_chrome_prebuilt(self, build_target, chroot, internal=False,
                          ignore_prebuilts=False):
    if ignore_prebuilts or self._deps_isolate:
      return False
    return self.m.cros_build_api.PackageService.HasChromePrebuilt(
        HasChromePrebuiltRequest(build_target=build_target, chroot=chroot,
                                 chrome=internal)).has_prebuilt

  def needs_chrome(self, build_target, chroot, packages=None):
    """Returns whether or not this run needs chrome.

    Returns whether or not this run needs chrome, that is, will require a
    prebuilt, or will need to build it from source.

    Args:
      build_target (chromiumos.BuildTarget): Build target of the build.
      chroot (chromiumos.Chroot): Information on the chroot for the build.
      packages (list[chromiumos.PackageInfo]): Packages that the builder needs
          to build, or empty / None for default packages.

    Returns:
      bool: Whether or not this run needs chrome.
    """
    return self.m.cros_build_api.PackageService.BuildsChrome(
        BuildsChromeRequest(
            build_target=build_target,
            chroot=chroot,
            packages=packages)).builds_chrome
