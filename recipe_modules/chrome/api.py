# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

from recipe_engine import recipe_api

from PB.chromite.api import packages
from PB.chromite.api.packages import BuildsChromeRequest
from PB.chromite.api.packages import GetChromeVersionRequest
from PB.chromite.api.packages import HasChromePrebuiltRequest
from PB.chromite.api.packages import HasPrebuiltRequest
from PB.chromite.api.packages import UprevVersionedPackageRequest
from PB.chromite.api.packages import NeedsChromeSourceRequest
from PB.chromite.api.packages import NeedsChromeSourceResponse
from PB.chromiumos.common import PackageInfo

CHROMIUM_CACHE_DIR = '/preload/chrome_cache'

# The following project->regexes should trigger a chrome rebuild.
CHROMIUM_REBUILD_REGEXES = {
    'chromiumos/overlays/chromiumos-overlay': [
        re.compile('chromeos-base/chromeos-chrome/'
                   'chromeos-chrome-[0-9].+\.ebuild$')
    ],
}

CHROME_PACKAGE = PackageInfo(category='chromeos-base',
                             package_name='chromeos-chrome')

# The following packages need chrome source to be synced to build.
# Consider adding to chromite/lib/constants.py under OTHER_CHROME_PACKAGES
# to prevent rebuilds (which may not succeed if chrome source isn't sync'd).
CHROME_FOLLOWER_PACKAGES = [
    ('chromeos-base', 'chrome-icu'),
]


class ChromeApi(recipe_api.RecipeApi):

  def __init__(self, properties, *args, **kwargs):
    super(ChromeApi, self).__init__(*args, **kwargs)
    self._parallel_sync_jobs = 4
    if properties.parallel_sync_jobs > 0:
      self._parallel_sync_jobs = properties.parallel_sync_jobs
    self._deps_isolate = (
        properties.deps_isolate
        if properties.HasField('deps_isolate') else None)
    self._version = properties.version

  def _get_local_version(self, chroot, build_target):
    """Returns chrome version from local chroot (e.g. "84.0.4109.1")."""
    request = packages.GetChromeVersionRequest(chroot=chroot,
                                               build_target=build_target)
    return self.m.cros_build_api.PackageService.GetChromeVersion(
        request, infra_step=True).version

  def sync(self, chrome_root, chroot, build_target, internal):
    """Sync Chrome source code.

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
        version = self._get_local_version(chroot, build_target)

      self.m.file.ensure_directory('ensure chrome root', chrome_root)

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
          self.m.isolated.download(
              'download DEPS from isolated', self._deps_isolate.isolated_hash,
              chrome_root, isolate_server=self._deps_isolate.isolate_server)
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

        for retries in range(self.test_api.gclient_sync_max_retries):
          try:
            with self.m.depot_tools.on_path():
              # Writes out the .gclient file.
              self.m.python('gclient config',
                            self.m.depot_tools.root.join('gclient.py'),
                            config_cmd, infra_step=True)

              # Reads what we just wrote for user consumption.
              gclient_text = (
                  self.m.file.read_text(
                      'gclient contents', chrome_root.join('.gclient'),
                      test_data='solutions = [ {"name":"src"}]'))
              pres.logs['gclient configuration'] = gclient_text.splitlines()

              # Finally, start the sync.
              self.m.python('gclient sync',
                            self.m.depot_tools.root.join('gclient.py'),
                            sync_cmd, infra_step=True,
                            timeout=self.test_api.gclient_sync_timeout_seconds)
              break
          except recipe_api.StepFailure as ex:
            if (ex.had_timeout and
                retries < self.test_api.gclient_sync_max_retries - 1):
              self.m.file.rmcontents('clean up root path and retry',
                                     chrome_root)
              self.m.time.sleep(self.test_api.gclient_sync_sleep_seconds)
            else:
              raise

  def diffed_files_requires_rebuild(self, patch_sets=None):
    """Returns a bool if patch_sets includes files that require rebuilding.

    The patch_sets object supplied must have been constructed with the file
    information populated.

    Args:
      patch_sets (list[gerrit.PatchSet]): List of patch sets (with FileInfo).

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
        BuildsChromeRequest(build_target=build_target, chroot=chroot,
                            packages=packages)).builds_chrome

  def follower_lacks_prebuilt(self, build_target, chroot, packages):
    """Returns whether we need the chrome source to be synced.

    Returns whether or not this run needs chrome source to be synced locally.
    This is independent of if we need to actually build chrome, as we've
    allowed 'follower' packages to be built out of chrome's source.

    Args:
      build_target (chromiumos.BuildTarget): Build target of the build.
      chroot (chromiumos.Chroot): Information on the chroot for the build.
      packages (list[chromiumos.PackageInfo]): Packages that the builder needs
          to build.
    Returns:
      bool: Whether or not this run needs chrome.
    """
    # If the synced to chromite build API does not implement HasPrebuilt, we'll
    # assume we are before the window where such followers existed, and return
    # false.
    if not self.m.cros_build_api.has_endpoint(
        self.m.cros_build_api.PackageService, 'HasPrebuilt'):
      return False

    # We'll first query the packages we're going to build out of the dependent
    # packages to get the versions and if it's necessary to build at all.
    with self.m.step.nest('any followers lack prebuilts') as pres:
      packageInfos = [
          p for p in packages
          if (p.category, p.package_name) in CHROME_FOLLOWER_PACKAGES
      ]

      # If any follower packages lack prebuilts, return True.
      any_lack_pb = any([
          not self.m.cros_build_api.PackageService.HasPrebuilt(
              HasPrebuiltRequest(build_target=build_target, chroot=chroot,
                                 package_info=p)).has_prebuilt
          for p in packageInfos
      ])
      pres.step_text = str(any_lack_pb)
      return any_lack_pb

  def maybe_uprev_local_chrome(self, build_target, chroot, patch_sets):
    """Checks the patch_sets for chrome 9999 ebuild changes and uprevs if so.

    Args:
      build_target (chromiumos.BuildTarget): Build target of the build.
      chroot (chromiumos.Chroot): Information on the chroot for the build.
      patch_sets (list[gerrit.PatchSet]): A list of patch sets to examine.

    Returns:
      bool: If we upreved the local Chrome.
    """
    if self.diffed_files_requires_rebuild(patch_sets=patch_sets):
      with self.m.step.nest('try uprev chrome'):
        version = self._get_local_version(chroot, build_target)
        version_ref = UprevVersionedPackageRequest.GitRef(
            repository='/chromium/src', ref='refs/tags/%s' % version,
            revision='deadbeefdeadbeefdeadbeefdeadbeefdeadbeef')
        request = UprevVersionedPackageRequest(
            chroot=chroot,
            package_info=CHROME_PACKAGE,
            versions=[version_ref],
            build_targets=[build_target],
        )
        response = self.m.cros_build_api.PackageService.UprevVersionedPackage(
            request, name='uprev local chrome package')
        return True
    return False

  def needs_chrome_source(self, request, dep_graph, presentation,
                          patch_sets=None):
    """Checks whether chrome source is needed.

    Args:
      request (InstallPackagesRequest): InstallPackagesRequest for the build.
      dep_graph (DepGraph): From cros_relevance.get_dependency_graph.
      presentation (StepPresentation): Step to update.
      patch_sets (list[gerrit.PatchSet]): Applied patchsets.  Default: the list
        from workspace_util.

    Returns:
      bool: Whether Chrome source is needed.
    """
    patch_sets = patch_sets or self.m.workspace_util.patch_sets

    # TODO(https://crbug.com/1086714): NeedsChromeSource is temporarily removed,
    # remove the "#pragma: nocover" when it comes back.
    # If there is a NeedChromeSource endpoint, use that.
    if self.m.cros_build_api.has_endpoint(
        self.m.cros_build_api.PackageService,
        'NeedsChromeSource'):  #pragma: nocover
      response = self.m.cros_build_api.PackageService.NeedsChromeSource(
          NeedsChromeSourceRequest(install_request=request))
    else:
      # Here we implement a (buggy) version of NeedsChromeSource.
      # TODO(crbug/1086714): Drop this (incomplete) code once bisection does not
      # need us to keep it.
      _type = NeedsChromeSourceResponse
      response = _type()
      chroot = request.chroot
      target = request.sysroot.build_target
      ignore_prebuilts = (
          request.flags.compile_source or request.flags.toolchain_changed)

      # Only bother to do these checks if the build target needs chrome src.
      if self.needs_chrome(target, chroot, packages=request.packages):

        # TODO(crbug.com/1086714): Remove dep_graph access and corresponding
        # use, we shouldn't be inspecting this, rather, call the build api.
        flattened_packages = []
        for package in dep_graph.target.package_deps:
          for dep_package in package.dependency_packages:
            flattened_packages.append(dep_package)

        response.builds_chrome = True
        raw_reasons = [
            _type.NO_PREBUILT if not self.has_chrome_prebuilt(
                target, chroot, ignore_prebuilts=ignore_prebuilts) else None,
            _type.LOCAL_UPREV if self.maybe_uprev_local_chrome(
                target, chroot, patch_sets) else None,
            _type.FOLLOWER_LACKS_PREBUILT if self.follower_lacks_prebuilt(
                target, chroot, flattened_packages) else None,
        ]
        response.reasons.extend([r for r in raw_reasons if r])
        response.needs_chrome_source = response.reasons != []

    # AKA: "Chrome Source Needed Reason".  Create the dictionary of all possible
    # reasons (ignoring UNSPECIFIED), which we will then
    csnr = {
        k.lower(): v in response.reasons
        for k, v in NeedsChromeSourceResponse.Reason.items()
        if v
    }
    presentation.step_text = (' '.join(k for k, v in csnr.items() if v) or
                              'not needed')
    self.m.easy.set_properties_step(chrome_source_reasons=csnr,
                                    builds_chrome=response.builds_chrome)

    return response.needs_chrome_source
