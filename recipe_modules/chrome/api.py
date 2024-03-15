# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import re

from pathlib import Path
from typing import Optional, List

from recipe_engine import recipe_api
from recipe_engine.engine_types import StepPresentation
from recipe_engine.recipe_api import StepFailure
from RECIPE_MODULES.chromeos.gerrit.api import PatchSet

from PB.chromite.api.depgraph import DepGraph
from PB.chromite.api.packages import BuildsChromeRequest
from PB.chromite.api.packages import GetChromeVersionRequest
from PB.chromite.api.packages import HasChromePrebuiltRequest
from PB.chromite.api.packages import HasPrebuiltRequest
from PB.chromite.api.packages import UprevVersionedPackageRequest
from PB.chromite.api.packages import NeedsChromeSourceRequest
from PB.chromite.api.packages import NeedsChromeSourceResponse
from PB.chromite.api.sysroot import InstallPackagesRequest
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget, Chroot, PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.chrome.chrome import ChromeProperties

CHROMIUM_GIT_URL = 'https://chromium.googlesource.com/chromium/src.git'

INTERNAL_GERRIT_HOST = 'chrome-internal-review.googlesource.com'

DEFAULT_GCLIENT_SYNC_TIMEOUT_SECONDS = 10800  # 3 hrs.

# This cache config is a slightly strange json format in that it needs the
# python preference for capitalized bools. Instead of json.dumps, just
# explicitly format this as needed. (See legacy build step SyncChrome.)
GCLIENT_CACHE_CONFIG = '''[
    {
        'url': '%s',
        'managed': False,
        'name': 'src',
        'custom_deps': {},
        'custom_vars': {
            'checkout_src_internal': True,
            'checkout_google_internal': True
        }
    }
]''' % CHROMIUM_GIT_URL  # Intentionally not using .format so custom_deps works.

# The following project->regexes should trigger a chrome rebuild.
CHROMIUM_REBUILD_REGEXES = {
    'chromiumos/overlays/chromiumos-overlay': [
        re.compile('chromeos-base/chromeos-chrome/'
                   r'chromeos-chrome-[0-9].+\.ebuild$')
    ],
}

# Gerrit topic for the chrome atomic uprev CLs
TOPIC_CHROME_UPREV_LACROS_ASH_ATOMIC = 'chromeos-base/lacros-ash-atomic'
# Cq-Cl-Tag footer value for the chrome atomic uprev CLs
CL_TAG_CHROME_UPREV_LACROS_ASH_ATOMIC = 'pupr:chromeos-base/lacros-ash-atomic'

CHROME_PACKAGE = PackageInfo(category='chromeos-base',
                             package_name='chromeos-chrome')

# The following packages need chrome source to be synced to build.
# Consider adding to chromite/lib/constants.py under OTHER_CHROME_PACKAGES
# to prevent rebuilds (which may not succeed if chrome source isn't sync'd).
CHROME_FOLLOWER_PACKAGES = [
    ('chromeos-base', 'chrome-icu'),
]


class ChromeApi(recipe_api.RecipeApi):
  """Module for managing chrome source code.

  Note: in general, ChromeOS builders check out the source code at a specific
  version. That version is obtained by hitting the BuildAPI to read an overlay,
  which requires a sysroot. This module includes some code to support speeding
  up those chrome checkouts by doing the following:
    - checkout the chrome source to the latest commit in the cache asynchronously
      with all refs and tags (sync_chrome_async).
    - wait for the async main sync (wait_for_sync_chrome_source_async).
    - delete the checkout of main (delete_chrome_checkout) for cases where it is
      unused.

  This supports the general workflow on all builders of:
    1.  As early as possible, kick off an async chrome checkout to the latest
          commit in the cache.
    2.  Whenever chrome source is definitely going to be needed, block and wait
          for that async checkout to complete.
    3a. If the chrome source code isn't needed, delete the checkout.
    3b. If the chrome source code is needed, check out the specific version
          needed (much faster with the repo already checked out).
  """

  @property
  def gclient_sync_timeout_seconds(self) -> int:
    return self._gclient_sync_timeout_seconds

  def __init__(self, properties: ChromeProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._deps_cas = (
        properties.deps_cas if properties.HasField('deps_cas') else None)
    self._version = properties.version

    self._gclient_sync_timeout_seconds = (
        properties.gclient_sync_timeout_seconds or
        DEFAULT_GCLIENT_SYNC_TIMEOUT_SECONDS)

    self._parallel_runner = None
    self._chrome_root = None

  def _get_local_version(self, chroot: Chroot,
                         build_target: BuildTarget) -> str:
    """Returns chrome version from local chroot (e.g. "84.0.4109.1")."""
    request = GetChromeVersionRequest(chroot=chroot, build_target=build_target)
    return self.m.cros_build_api.PackageService.GetChromeVersion(
        request, infra_step=True).version

  def cache_sync(self, cache_path: Path, sync: bool = True,
                 step_name: str = 'sync chrome') -> None:
    """Sync Chrome cache using existing cached repositories.

    Args:
      cache_path: Path to mount of cache.
      sync: whether or not to call sync after setting up the cache. Defaults to true.
      step_name: the name to use for the surrounding step. Defaults to "sync chrome".

    """
    with self.m.step.nest(step_name):
      src_dir = cache_path.join('src')
      self.m.file.ensure_directory('ensure chrome src directory', src_dir)
      self.m.file.ensure_directory('ensure chrome cache directory',
                                   cache_path.join('chrome_cache'))
      config_exists = self.m.path.exists(src_dir.join('.gclient'))
      with self.m.context(cwd=src_dir), \
          self.m.depot_tools.on_path():
        if not config_exists:
          gclient_config_cmd = [
              'config', '--spec',
              "solutions = {}\ncache_dir = '../chrome_cache'".format(
                  GCLIENT_CACHE_CONFIG)
          ]
          self.m.gclient('config', gclient_config_cmd, infra_step=True)
        cache_cmd = [
            'populate',
            '-v',
            '--cache-dir',
            '../chrome_cache',
            CHROMIUM_GIT_URL,
            '--reset-fetch-config',
        ]
        self.m.step('populate git cache',
                    [self.m.depot_tools.root.join('git_cache.py')] + cache_cmd,
                    infra_step=True)
        if sync:
          gclient_sync_cmd = [
              'sync',
              '--reset',
              '--with_branch_heads',
              '--with_tags',
              '--verbose',
          ]
          self.m.gclient('sync', gclient_sync_cmd, infra_step=True,
                         timeout=self.gclient_sync_timeout_seconds)

  def sync_chrome_async(self, config: BuilderConfig,
                        build_target: BuildTarget) -> None:
    """Sync chrome source async.

    Intentionally checking out the chrome source on main instead of the
    appropriate version for the build. The purpose is to speed up the
    subsequent chrome source sync.

    Args:
      config: The Builder Config for the build.
      build_target: Build target of the build.
    """

    def _get_cache_head() -> Optional[str]:
      src_dir = self._chrome_root.join('chrome_cache').join(
          'chromium.googlesource.com-chromium-src')
      head_file = src_dir.join('HEAD')
      regex = re.search(r'(?<=ref:\s)\S+',
                        self.m.file.read_text('read HEAD ref', head_file))
      if regex:
        head_ref = regex.group(0)
      else:
        return None
      return self.m.file.read_text('read HEAD hash',
                                   src_dir.join(head_ref)).replace('\n', '')

    def _sync_chrome_source(builder_config: BuilderConfig) -> None:
      with self.m.step.nest('sync chrome source async'):
        chrome_root = self._chrome_root
        self.cache_sync(cache_path=chrome_root, sync=False,
                        step_name='populate chrome cache')
        with self.m.step.nest('find chrome cache head'):
          cache_head = _get_cache_head()
        self.m.easy.set_properties_step(chrome_cache_head=cache_head)
        self.sync(chrome_root, self.m.cros_sdk.chroot, build_target,
                  builder_config.chrome.internal,
                  cache_dir=chrome_root.join('chrome_cache'),
                  override_version=cache_head, omit_version=not cache_head)

    self._chrome_root = self.m.path['start_dir'].join('chrome')
    self._parallel_runner = self.m.future_utils.create_parallel_runner()
    self._parallel_runner.run_function_async(
        lambda cfg, _: _sync_chrome_source(cfg), config)

  def wait_for_sync_chrome_source_async(self) -> None:
    """Wait for async chrome source sync."""
    if self._parallel_runner:
      self._parallel_runner.wait_for_and_throw()

  def delete_chrome_checkout(self) -> None:
    """Delete unnecessary chrome checkout.

    Allows to delete the chrome source synced in sync_chrome_async() function when it
    turns out to be unnecessary for the build.
    """
    if self._chrome_root:
      self.m.file.rmtree('deleting chrome checkout', self._chrome_root)

  def sync(self, chrome_root: Path, chroot: Chroot, build_target: BuildTarget,
           internal: bool, cache_dir: str,
           override_version: Optional[str] = None,
           omit_version: bool = False) -> None:
    """Sync Chrome source code.

    Must be run with cwd inside a chromiumos source root.

    Args:
      chrome_root: Directory to sync the Chrome source code to.
      chroot: Information on the chroot for the build.
      build_target: Build target of the build.
      internal: True for internal checkout.
      cache_dir: Path of the chrome cache.
      override_version: Specific git ref/hash to sync to.
      omit_version: Omit the version from the sync command. Defaults to False.
    """
    with self.m.step.nest('sync chrome') as pres:
      if override_version:
        version = override_version
      elif omit_version:
        version = None
      else:
        if self._version or self._deps_cas:
          version = self._version
        else:
          version = self._get_local_version(chroot, build_target)

      self.m.file.ensure_directory('ensure chrome root', chrome_root)

      # Similar to what you would get with self.m.gclient.checkout approach
      # but here we up the job parallelism for a speed boost.
      with self.m.context(cwd=chrome_root):
        cfg = self.m.gclient.make_config(CACHE_DIR=cache_dir)
        cfg.target_os = ['chromeos']
        soln = cfg.solutions.add()
        soln.name = 'src'
        soln.url = 'https://chromium.googlesource.com/chromium/src.git'
        soln.custom_vars = {
            'checkout_src_internal': internal,
        }
        if self._deps_cas:
          self.m.cas.download('download DEPS from cas', self._deps_cas.digest,
                              chrome_root)
          soln.deps_file = str(chrome_root) + '/DEPS'
          self.m.file.read_text('read DEPS', soln.deps_file, test_data='DEPS')

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
          # Define the step call with exp retry attached, pass self to help tests
          # see the context (inside of util) and elide the sleep.
          @self.m.time.exponential_retry(retries=1,
                                         delay=datetime.timedelta(seconds=120))
          def _call_chrome_sync(self) -> None:
            try:
              # Writes out the .gclient file.
              self.m.gclient('config', config_cmd, infra_step=True)

              # Reads what we just wrote for user consumption.
              gclient_text = (
                  self.m.file.read_text(
                      'gclient contents', chrome_root.join('.gclient'),
                      test_data='solutions = [ {"name":"src"}]'))
              pres.logs['gclient configuration'] = gclient_text.splitlines()

              # Finally, start the sync.

              self.m.gclient('sync', sync_cmd, infra_step=True,
                             timeout=self.gclient_sync_timeout_seconds)
            except StepFailure:
              self.m.file.rmcontents('clean up root path and retry',
                                     chrome_root)
              raise

          _call_chrome_sync(self)

  def diffed_files_requires_rebuild(
      self, patch_sets: Optional[List[PatchSet]] = None) -> bool:
    """Returns a bool if patch_sets includes files that require rebuilding.

    The patch_sets object supplied must have been constructed with the file
    information populated.

    Args:
      patch_sets: List of patch sets (with FileInfo).

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

  def is_chrome_pupr_atomic_uprev(self, gerrit_change: GerritChange) -> bool:
    # Check the host.
    if gerrit_change.host == INTERNAL_GERRIT_HOST:
      return False

    # Check the 'Cq-Cl-Tag' field in the description.
    cl_tags = self.m.git_footers.get_footer_values([gerrit_change], 'Cq-Cl-Tag')
    if len(cl_tags) == 0:
      return False
    cl_tag = next(iter(cl_tags))
    if cl_tag != CL_TAG_CHROME_UPREV_LACROS_ASH_ATOMIC:
      return False

    patch_sets = self.m.gerrit.fetch_patch_sets([gerrit_change],
                                                include_files=True)

    # Check the topic.
    if patch_sets[0].topic != TOPIC_CHROME_UPREV_LACROS_ASH_ATOMIC:
      return False

    # Check the ebuild file change is in the patch set.
    return self.diffed_files_requires_rebuild(patch_sets)

  def has_chrome_prebuilt(self, build_target: BuildTarget, chroot: Chroot,
                          internal: bool = False,
                          ignore_prebuilts: bool = False) -> bool:
    if ignore_prebuilts or self._deps_cas:
      return False
    return self.m.cros_build_api.PackageService.HasChromePrebuilt(
        HasChromePrebuiltRequest(build_target=build_target, chroot=chroot,
                                 chrome=internal)).has_prebuilt

  def needs_chrome(self, build_target: BuildTarget, chroot: Chroot,
                   packages: Optional[List[PackageInfo]] = None) -> bool:
    """Returns whether or not this run needs chrome.

    Returns whether or not this run needs chrome, that is, will require a
    prebuilt, or will need to build it from source.

    Args:
      build_target: Build target of the build.
      chroot: Information on the chroot for the build.
      packages: Packages that the builder needs
          to build, or empty / None for default packages.

    Returns:
      bool: Whether or not this run needs chrome.
    """
    return self.m.cros_build_api.PackageService.BuildsChrome(
        BuildsChromeRequest(build_target=build_target, chroot=chroot,
                            packages=packages)).builds_chrome

  def follower_lacks_prebuilt(self, build_target: BuildTarget, chroot: Chroot,
                              packages: List[PackageInfo]) -> bool:
    """Returns whether we need the chrome source to be synced.

    Returns whether or not this run needs chrome source to be synced locally.
    This is independent of if we need to actually build chrome, as we've
    allowed 'follower' packages to be built out of chrome's source.

    Args:
      build_target: Build target of the build.
      chroot: Information on the chroot for the build.
      packages: Packages that the builder needs to build.
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
      any_lack_pb = any(not self.m.cros_build_api.PackageService.HasPrebuilt(
          HasPrebuiltRequest(build_target=build_target, chroot=chroot,
                             package_info=p)).has_prebuilt
                        for p in packageInfos)
      pres.step_text = str(any_lack_pb)
      return any_lack_pb

  def maybe_uprev_local_chrome(self, build_target: BuildTarget, chroot: Chroot,
                               patch_sets: List[PatchSet]) -> bool:
    """Checks the patch_sets for chrome 9999 ebuild changes and uprevs if so.

    Args:
      build_target: Build target of the build.
      chroot: Information on the chroot for the build.
      patch_sets: A list of patch sets to examine.

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
        self.m.cros_build_api.PackageService.UprevVersionedPackage(
            request, name='uprev local chrome package')
        return True
    return False

  def _fallback_needs_chrome_source(
      self, request: InstallPackagesRequest, dep_graph: DepGraph,
      patch_sets: Optional[List[PatchSet]] = None) -> NeedsChromeSourceResponse:
    """Legacy fallback to check whether chrome source is needed.

    Args:
      request: InstallPackagesRequest for the build.
      dep_graph: From cros_relevance.get_dependency_graph.
      patch_sets: Applied patchsets. Default: the list from workspace_util.

    Returns:
      NeedsChromeSourceResponse: Response from BuildAPI
    """
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

    return response

  def needs_chrome_source(self, request: InstallPackagesRequest,
                          dep_graph: DepGraph, presentation: StepPresentation,
                          patch_sets: Optional[List[PatchSet]] = None) -> bool:
    """Checks whether chrome source is needed.

    Args:
      request: InstallPackagesRequest for the build.
      dep_graph: From cros_relevance.get_dependency_graph.
      presentation: Step to update.
      patch_sets: Applied patchsets. Default: the list from workspace_util.

    Returns:
      bool: Whether Chrome source is needed.
    """
    patch_sets = patch_sets or self.m.workspace_util.patch_sets

    # If there is a NeedChromeSource endpoint, use that.
    if self.m.cros_build_api.has_endpoint(
        self.m.cros_build_api.PackageService,
        'NeedsChromeSource'):  #pragma: nocover
      try:
        response = self.m.cros_build_api.PackageService.NeedsChromeSource(
            NeedsChromeSourceRequest(install_request=request,
                                     chroot=self.m.cros_sdk.chroot))
      except StepFailure as e:
        with self.m.step.nest('ignored exception') as pres:
          pres.logs['caught exception'] = repr(e)
        response = self._fallback_needs_chrome_source(request=request,
                                                      dep_graph=dep_graph,
                                                      patch_sets=patch_sets)
    else:
      response = self._fallback_needs_chrome_source(request=request,
                                                    dep_graph=dep_graph,
                                                    patch_sets=patch_sets)
    # AKA: "Chrome Source Needed Reason".  Create the dictionary of all possible
    # reasons (ignoring UNSPECIFIED), which we will then
    csnr = {
        k.lower(): v in response.reasons
        for k, v in NeedsChromeSourceResponse.Reason.items()
        if v
    }
    presentation.step_text = (' '.join(k for k, v in sorted(csnr.items()) if v)
                              or 'not needed')
    self.m.easy.set_properties_step(chrome_source_reasons=csnr,
                                    builds_chrome=response.builds_chrome)

    return response.needs_chrome_source
