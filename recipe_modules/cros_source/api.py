# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS source."""
import datetime
from collections import defaultdict
from collections import OrderedDict
from collections import namedtuple
import contextlib
import copy
import multiprocessing
import re
from typing import Any, Dict, List, Optional, OrderedDict as OrderedDict_type

from google.protobuf.json_format import MessageToDict

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import InfraFailure
from recipe_engine.recipe_api import StepFailure
from recipe_engine.config_types import Path

from PB.chromite.api.packages import UprevPackagesRequest
from PB.chromite.api.binhost import OVERLAYTYPE_BOTH
from PB.chromiumos import builder_config as builder_config_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.recipe_modules.chromeos.cros_source.cros_source import GitStrategy
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

# Default sync options for syncing the named cache.
DEFAULT_CACHE_SYNC_OPTS = {
    'current_branch': True,
    'detach': True,
    'force_sync': True,
    'jobs': 8,
    'no_tags': True,
    'optimized_fetch': True,
    'retry_fetches': 8,
    'timeout': 3600,
    'force_remove_dirty': True,
    'prune': True,
}

STAGING_INIT_OPTS = {'repo_branch': 'main'}

# Default options for checking out a branch.
DEFAULT_CHECKOUT_SYNC_OPTS = {
    'current_branch': True,
    'force_sync': True,
    'jobs': 8,
    'optimized_fetch': True,
    'retry_fetches': 8,
    'timeout': 10800,
}

# Manifest repositories that sync_to_pinned_manifest is allowed to pull from.
ALLOWED_MANIFEST_SOURCES = [
    'https://chrome-internal.googlesource.com/chromeos/manifest-internal',
    'https://chrome-internal.googlesource.com/chromeos/manifest-versions',
    'https://chromium.googlesource.com/chromiumos/manifest',
]


class CrosSourceApi(RecipeApi):
  """A module for CrOS-specific source steps."""
  # TODO(b/192099206): add default values when recipe upgrades to python3
  # PushUprevRequest:
  #   modified_files (list[path]): Path to modified file.
  #   message_subject (string): String to use as the commit subject.
  PushUprevRequest = namedtuple('PushUprevRequest', [
      'modified_files',
      'message_subject',
  ])

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._snapshot_cas = (
        properties.snapshot_cas
        if properties.HasField('snapshot_cas') else None)
    self._is_source_dirty = bool(self._snapshot_cas)
    self._sync_to_manifest = properties.sync_to_manifest
    self._recovery_snapshot = properties.recovery_source_cache_snapshot
    self._use_external_source_cache = properties.use_external_source_cache
    self._cache_name = 'chromiumos' if properties.use_external_source_cache else 'chromeos'
    # The currently active branch of the manifest.  Empty unless we switched
    # branches.
    self._manifest_branch = ''
    # (XML data) The pinned manifest for this build.
    self._pinned_manifest = None
    # (Path) either manifest-internal/snapshot.xml, or (unpinned) manifest.xml.
    self._branch_manifest_file = None
    self._applied_patches = defaultdict(list)
    self._have_overlayfs_cleanup_context = False
    self._workspace_mounted = False
    # Set whenever we sync the workspace, rather than remaining on "whatever the
    # chromiumos named cache gave us".
    self._sync_target = {}
    self._is_configured = False
    self.git_strategy = GitStrategy.CHERRY_PICK

  def initialize(self):
    """Initialization that follows all module loading."""
    # Check if there is already a workspace directory, and note that.
    # See b/188555398.
    workspace = self.m.path.start_dir / 'chromiumos_workspace'
    if self.m.path.exists(workspace):
      with self.m.step.nest('found pre-existing {}'.format(str(workspace))):
        self.m.easy.set_properties_step(preexisting_workspace=True)
        with self.m.context(cwd=workspace):
          self.m.step('ls', ['ls', '-l'])
          self.m.step('mounts', ['cat', '/proc/mounts'])

  @property
  def mirrored_manifest_files(self):
    """Returns the names of files that are mirrored into the public manifest.

    The files returned are owned by chromeos/manifest-internal, and are copied
    into chromiumos/manifest when they are changed.

    Annealing does this as part of creating the snapshot, and the various
    builders do it when applying manifest changes.

    Returns:
      (list[MirroredManifestFile]) with files we mirror.
    """

    MirroredManifestFile = namedtuple('MirroredManifestFile', 'src dest')
    return [
        MirroredManifestFile('codesearch-chromiumos.xml',
                             'codesearch-chromiumos.xml'),
        MirroredManifestFile('full.xml', 'full.xml'),
        MirroredManifestFile('external_full.xml', 'full.xml'),
        MirroredManifestFile('_kernel_upstream.xml', '_kernel_upstream.xml'),
        MirroredManifestFile('_remotes.xml', '_remotes.xml'),
        MirroredManifestFile('_toolchain.xml', '_toolchain.xml'),
        MirroredManifestFile('DIR_METADATA', 'DIR_METADATA'),
        MirroredManifestFile('README.md', 'README.md'),
    ]

  @property
  def pinned_manifest(self):
    """Return the pinned manifest for this build."""
    with self.m.context(cwd=self.workspace_path):
      self._pinned_manifest = (
          self._pinned_manifest or self.m.repo.manifest(pinned=True))
      return self._pinned_manifest

  @property
  def branch_manifest_file(self):
    """Returns the Path to the manifest_file for this build."""
    return (self._branch_manifest_file or
            self.m.src_state.internal_manifest.path / 'snapshot.xml')

  @property
  def manifest_branch(self):
    """Returns any non-default manifest branch that is checked out."""
    if self._test_data.enabled and self.test_api.manifest_branch:
      return self.test_api.manifest_branch
    return self._manifest_branch

  @property
  def is_tot(self):
    """Return whether or not the builder is on ToT."""
    return self.manifest_branch in ['', 'main', 'snapshot', 'staging-snapshot']

  @property
  def manifest_push(self):
    """Returns the manifest branch to push changes to."""
    ret = self.manifest_branch
    ret = 'main' if ret in ('snapshot', 'staging-snapshot', '') else ret
    return ret

  @property
  def sync_to_manifest(self):
    """Returns the manifest being synced to as specified in properties, or None.

      Uses the `sync_to_manifest` property.

      Returns: ManifestLocation, or None.
    """
    if self._sync_to_manifest is None or (
        not self._sync_to_manifest.manifest_repo_url and
        not self._sync_to_manifest.manifest_gs_path):
      return None
    return self._sync_to_manifest

  @property
  def is_source_dirty(self):
    """Returns whether the source is dirty.

    Returns whether the source is dirty. The source is dirty if it was checked
    out to a custom snapshot from isolate or has had patches applied or has
    been moved to a branch.
    """
    return self._is_source_dirty

  @property
  def cache_path(self):
    """The cached checkout path.

    This is the cached version of source (the internal manifest checkout),
    usually updated once at the beginning of a build and then mounted into the
    workspace path.
    """
    return self.m.path.cache_dir / self._cache_name

  @property
  def workspace_path(self):
    """The "workspace" checkout path.

    This is where the build is processed. It will contain the target base
    checkout and any modifications made by the build.
    """
    return self.m.src_state.workspace_path

  @property
  def snapshot_cas_digest(self):
    """Returns the snapshot digest in use or None."""
    return self._snapshot_cas.digest if self._snapshot_cas else None

  @property
  def use_external_source_cache(self):
    """Returns whether the builder is configured to use the external cache."""
    return self._use_external_source_cache

  def _clear_applied_patches_list(self):
    """Empty out the stored list of applied patches."""
    self._applied_patches = defaultdict(list)

  def _determine_sync_jobs(self):
    """Determines the number of jobs to use for sync based on CPUs."""
    if self._test_data.enabled:
      jobs = 8
    elif multiprocessing.cpu_count() > 32:  #pragma: no cover
      jobs = 32
    else:  #pragma: no cover
      jobs = multiprocessing.cpu_count()
    return jobs

  def configure_builder(
      self,
      commit: Optional[bb_common_pb2.GitilesCommit] = None,
      changes: Optional[List[bb_common_pb2.GerritChange]] = None,
      default_main: bool = False,
      name: str = 'configure builder',
      lookup_config_with_bucket=False,
  ) -> Optional[builder_config_pb2.BuilderConfig]:
    """Configure the builder.

    Fetch the builder config.
    Determine the actual commit and changes to use.
    Set the bisect_builder and use_flags.

    Args:
      commit: The gitiles commit to use.  Default:
        GitilesCommit(.... ref='refs/heads/snapshot').
      changes: The gerrit changes to apply.  Default: the gerrit_changes from
        buildbucket.
      default_main: Whether the default branch should be 'main'. Default: use
        the appropriate snapshot branch.
      name: Step name.
      lookup_config_with_bucket: If true, include builder.bucket in key when
        looking up the BuilderConfig. If the bucket is not included in the key
        and there are builders with the same name (in different buckets), it is
        undefined which BuilderConfig is returned. The bucket will eventually
        be included in the key by default, see b/287633203.

    Returns:
      BuilderConfig for the active build, or None if the active build does not
      have a BuilderConfig.
    """
    branch_fmt = (r'(?P<branch>(?P<base>(factory|firmware|release|stabilize)-'
                  r'(((?P<device>[-a-zA-Z_0-9.]+)|(?P<release>R[1-9][0-9]*))-)?'
                  r'(?P<version>[0-9.]+)'
                  r')\.B)'
                  r'(?P<parent_branch>-.+)?$')
    valid_branch = lambda b: re.match(branch_fmt, b)

    with self.m.step.nest(name=name):
      self._is_configured = True
      commit = commit or self.m.src_state.gitiles_commit
      changes = changes or self.m.src_state.gerrit_changes
      patch_sets = []
      if changes:
        patch_sets = self.m.gerrit.fetch_patch_sets(changes,
                                                    include_commit_info=True,
                                                    include_files=True)

      # If there is a change to infra/config in gerrit_changes, we want to use
      # that.  We need to determine that before we configure the builder, which
      # severely limits what we can do.  Only look for changes to the main
      # branch of chromeos/infra/config.
      config_patches = [
          x for x in patch_sets
          if x.project == 'chromeos/infra/config' and x.branch == 'main'
      ]

      # Use cases:
      # 1. CQ with a change to infra/config:
      #    The CQ build will proceed with the changed BuilderConfigs, running
      #    the verifiers caused by the other changes.
      #
      # 2. Non-CQ builder with a change to infra/config: (manually launched)
      #    If the config does not apply patches, the build will fail if a change
      #    is specified.  It's likely easier to use
      #    $chromeos/cros_infra_config.config_ref to apply the patch in this
      #    case.
      #
      # 3. Mulitple changes to infra/config: (NOT SUPPORTED)
      #    The answer here is: "developer merges the changes into one WIP CL and
      #    tests".
      #
      #    If the changes are all in a stack, the top of the stack (which has
      #    all of the changes in its copy of generated/builder_configs.cfg) can
      #    be passed via $chromeos/cros_infra_config.config_ref.
      #
      #    If the changes are not in one stack, we would need to fetch them all,
      #    merge them, and then add support to cros_infra_config to use the
      #    local (merged) file.
      config_ref = None
      if config_patches:
        if len(config_patches) > 1:
          raise StepFailure('Found more than one config patch: {}'.format(
              ' '.join(x.display_id for x in config_patches)))
        conf = config_patches[0]
        config_ref = 'refs/changes/%02d/%d/%d' % (
            conf.change_id % 100, conf.change_id, conf.patch_set)

      config = self.m.cros_infra_config.configure_builder(
          commit=commit, changes=changes, name='cros_infra_config',
          choose_branch=False, config_ref=config_ref,
          lookup_config_with_bucket=lookup_config_with_bucket)

      commit = self.m.src_state.gitiles_commit
      if not commit.ref:
        # Neither buildbucket, nor the builder config provided a gitiles_commit.
        # Figure out what gitiles_commit should be.

        branches = set()
        with self.m.step.nest('determine branch from changes') as pres:
          # If the change is on what looks like a valid branch, use that for the
          # checkout.
          for patch_set in patch_sets:
            branch = self.m.git.extract_branch(patch_set.branch,
                                               patch_set.branch)
            if valid_branch(branch):
              branches.add(re.sub(branch_fmt, r'\g<branch>', branch))

          if branches:
            # While not pedantically correct, some branches refer to other
            # branches for some projects in their manifest.  For example, see
            # the manifest for firmware-icarus-12574.B.
            #
            # If there are multiple branches, use the first one from the list,
            # rather than raising an error.  If we do switch to throwing an
            # error, we should add a git footer to allow it.
            branches = sorted(branches)
            branch = branches[0]
            branch_ref = self.m.git.get_branch_ref(branch)
            pres.step_text = 'Using manifest branch {}.  Found {}'.format(
                branch, ' '.join(branches))
            # Override gitiles_commit to use the appropriate ref/id.
            with self.m.step.nest('set src_state.gitiles_commit'):
              commit.ref = branch_ref
              commit.id = ''

      if not commit.ref:
        # If we do not have a commit ref, use the appropriate snapshot branch.
        if default_main:
          commit.ref = 'refs/heads/main'
        else:
          commit.ref = 'refs/heads/{}snapshot'.format(
              'staging-' if self.m.cros_infra_config.is_staging else '')

      # If there is no commit id, fetch the current commit id for the reference.
      if not commit.id:
        test_data = {
            'branch': {
                'revision': '%s-HEAD-SHA' % commit.ref.split('/')[-1],
            }
        }
        commit.id = self.m.gitiles.fetch_revision(commit.host, commit.project,
                                                  commit.ref,
                                                  test_output_data=test_data)

      # Record the decision for later.  Saving the values in src_state will log
      # what we chose to use (rather than what we were given.)
      self.m.src_state.gitiles_commit = commit

    return config

  def _validate_args(self, manifest_url, local_manifests, groups, cache_path):
    """Ensure the args to ensure_synced_cache are to a supported configuration.

    Supported configurations include:
      - INTERNAL: Sync the internal manifest to self.cache_path.
      - CUSTOM: Sync any manifest to any path other than
        self.cache_path.

    Args:
      manifest_url (str): Manifest URL for 'repo.init`.
      local_manifests (list[repo.LocalManifest]): List of local manifests to
        add or None if not syncing a local manifest.
      groups (list[str]): List of manifest groups to checkout.
      cache_path (Path): Path to sync into. If None, the cache_path
        property is used.
    Returns:
      If the configuration is supported, the type of configuration.
    """
    if cache_path == self.cache_path and self._cache_name == 'chromeos':
      if (manifest_url != self.m.src_state.internal_manifest.url or
          local_manifests or groups):
        raise ValueError('Only the internal manifest on the default branch can'
                         ' be synced to the chromeos cache path.')
      return 'INTERNAL'
    return 'CUSTOM'

  def ensure_synced_cache(
      self, manifest_url: Optional[str] = None,
      init_opts: Optional[Dict[str, Any]] = None,
      sync_opts: Optional[Dict[str, Any]] = None,
      cache_path_override: Optional[Path] = None, is_staging: bool = False,
      projects: Optional[List[str]] = None,
      gitiles_commit: Optional[bb_common_pb2.GitilesCommit] = None,
      manifest_branch_override: Optional[str] = None):
    """Ensure the configured repo cache exists and is synced.

    Args:
      manifest_url: Manifest URL for 'repo.init`.
      init_opts: Extra keyword arguments to pass to 'repo.init'.
      sync_opts: Extra keyword arguments to pass to 'repo.sync'.
      cache_path_override: Path to sync into. If None, the cache_path property
        is used.
      is_staging: Flag to indicate canary staging environment.
      projects : Projects to limit the sync to, or None to sync all projects.
      gitiles_commit: The gitiles_commit, or None to use the current value.
      manifest_branch_override: If provided, override the manifest_branch value
        in init_opts. Otherwise, use the value returned from
        configure_builder().
    """
    # Make sure that there is an active overlayfs.cleanup_context.
    # See crbug.com/1165775.
    assert self._have_overlayfs_cleanup_context, 'no overlayfs cleanup context'

    # This is purely a bug catcher to ease detection of the issue when someone
    # configures a builder incorrectly.
    assert self.m.bot_cost.bot_size not in [
        'f1-micro', 'g1-small', 'e2-medium', 'e2-small'
    ] or projects or ('groups' in init_opts), (
        'cannot sync full tree on small bot.')

    with self.m.context(cwd=self.m.path.cleanup_dir):
      # There are a few things we want to make sure are set globally for git.
      # Do them here to help protect the named cache from corruption due to
      # off-branch objects being removed.
      # Disable automatic garbage collection.  See https://crbug.com/1137935.
      self.m.git.set_global_config(['gc.auto', '0'])
      # Disable packRefs before doing merges. See https://crbug.com/1057878.
      self.m.git.set_global_config(['gc.packRefs', 'false'])

    assert self._is_configured, 'cros_source not configured'
    cache_path = cache_path_override or self.cache_path
    manifest_url = manifest_url or (self.m.src_state.internal_manifest.url
                                    if self._cache_name == 'chromeos' else
                                    self.m.src_state.external_manifest.url)
    # Only mount the workspace overlay if we are syncing directly to it.
    # This prevents code from accidently trashing their view of the source tree
    # by touching it before we sync the cache and create the overlayfs
    if cache_path == self.workspace_path and not self._workspace_mounted:
      self.m.overlayfs.mount('workspace', self.cache_path, self.workspace_path)
      self._prepare_bazel_cache()
      self.m.path.mock_add_paths(self.workspace_path / '.repo')
      self._workspace_mounted = True

    gitiles_commit = gitiles_commit or self.m.src_state.gitiles_commit
    gitiles_commit = (
        gitiles_commit if gitiles_commit.host else
        self.m.src_state.internal_manifest.as_gitiles_commit_proto)
    if cache_path == self.workspace_path:
      self._sync_target = {
          'call': 'ensure_synced_cache',
          'commit': MessageToDict(gitiles_commit),
      }

    init_opts = init_opts or {}
    # Initialize the cache on the branch given from configure_builder or the
    # override value. If an incorrect format is given then default to
    # (staging-)snapshot.
    # Visit go/cros-snapshot-source-cache-dd for more background.
    init_opts[
        'manifest_branch'] = manifest_branch_override or self.m.git.extract_branch(
            gitiles_commit.ref, '{}snapshot'.format(
                'staging-' if self.m.cros_infra_config.is_staging else ''))
    if is_staging:
      init_opts.update(STAGING_INIT_OPTS)
      # Allow forcing the released version of repo on staging.
      if ('chromeos.cros_source.use_released_repo_on_staging'
          in self.m.cros_infra_config.experiments):
        init_opts['repo_branch'] = None

    tmp_sync_opts = copy.deepcopy(DEFAULT_CACHE_SYNC_OPTS)
    tmp_sync_opts.update(sync_opts or {})
    tmp_sync_opts['jobs'] = self._determine_sync_jobs()
    sync_opts = tmp_sync_opts

    local_manifests = init_opts.get('local_manifests')
    groups = init_opts.get('groups')
    verbose = init_opts.get('verbose', True)
    manifest_branch = init_opts.get('manifest_branch')
    retry_fetches = sync_opts.get('retry_fetches')

    configuration = self._validate_args(manifest_url, local_manifests, groups,
                                        cache_path)
    if configuration == 'INTERNAL':
      self._sync_cached_dir(manifest_branch, retry_fetches=retry_fetches,
                            projects=projects, verbose=verbose,
                            is_staging=is_staging)
    else:
      if not self.m.repo.ensure_synced_checkout(
          cache_path, manifest_url, init_opts=init_opts, sync_opts=sync_opts,
          projects=projects):
        raise InfraFailure('failed to sync checkout')

      # Sync all branches of the build manifest, so that we can find branches.
      # If groups were specified, then the manifest project is probably not
      # present, so don't bother.
      if not groups:
        with self.m.step.nest('sync manifest branches'):
          for man in sorted(
              set([
                  self.m.src_state.build_manifest,
                  self.m.src_state.external_manifest
              ]), key=lambda x: x.url):
            with self.m.context(cwd=cache_path / man.relpath):
              step_name = 'sync {} branches'.format(man.project)
              self.m.git.remote_update(step_name=step_name)

    self._manifest_branch = manifest_branch or ''

    # Finally, create the workspace overlay.
    if cache_path != self.workspace_path:
      self.m.overlayfs.mount('workspace', self.cache_path, self.workspace_path)
      self._prepare_bazel_cache()
      self.m.path.mock_add_paths(self.workspace_path / '.repo')
      self._workspace_mounted = True

  def _prepare_bazel_cache(self):
    """Prepares the cache directory for Bazel.

    This function must be called immediately after mounting the overlayfs for
    the workspace directory. Since Bazel uses $workspace_dir/.cache/bazel for
    the output directory and it must not be on overlayfs, this function
    bind-mounts a non-overlayfs directory to the output directory path.
    """
    real_dir = self.m.path.cache_dir / 'bazel-cache'
    mount_dir = self.workspace_path / '.cache/bazel'
    self.m.file.ensure_directory('ensure bazel cache dir', real_dir)
    self.m.file.ensure_directory('ensure bazel cache mountpoint', mount_dir)
    # Note that we don't need to unmount this bind-mount explicitly because it
    # is recursively unmounted when the parent overlayfs is unmounted.
    self.m.step('bind mount bazel cache dir', [
        'sudo',
        '-n',
        'mount',
        '--bind',
        real_dir,
        mount_dir,
    ], infra_step=True)

  def _gitiles_branch(self, ref):
    """Return the branch for a gitiles_commit.ref"""
    branch = (
        ref[len('refs/heads/'):] if ref.startswith('refs/heads/') else ref)
    branch = '' if branch in ('snapshot', 'staging-snapshot') else branch
    return branch

  def get_external_snapshot_commit(self, internal_manifest_path: Path,
                                   snapshot_commit_id: str) -> Optional[str]:
    """Return the Cr-External-Snapshot for the given internal snapshot commit.

    The internal snapshot commit contains a footer 'Cr-External-Snapshot' which
    contains the corresponding snapshot commit in the external manifest.

    Note: This function assumes the internal manifest is synced.

    Args:
      internal_manifest_path: The path where the internal manifest is checked
        out.
      snapshot_commit_id: The internal snapshot commit id for which to return
        the external snapshot commit counterpart.

    Raises:
      StepFailure if there is not exactly one Cr-External-Snapshot footer.

    Returns:
      The corresponding exteral manifest snapshot commit.
    """
    with self.m.context(cwd=internal_manifest_path):
      test_data = self.m.git_footers.test_api.step_test_data_factory('e' * 40)
      footers = self.m.git_footers.from_ref(snapshot_commit_id,
                                            key='Cr-External-Snapshot',
                                            step_test_data=test_data)

      if not footers or len(footers) != 1:
        raise StepFailure('expected exactly one Cr-External-Snapshot footer')

      return footers[0]

  def checkout_external_manifest(self, commit_id: str, force: bool = True):
    """Checkout the external manifest at the given commit.

    Args:
      commit_id: The commit of the external manifest to checkout.
      force: If true, throw away any local changes.
    """
    with self.m.step.nest('checkout external manifest'), self.m.context(
        cwd=self.m.src_state.external_manifest.path):
      self.m.git.fetch(self.m.src_state.external_manifest.remote,
                       ['%s:' % commit_id])
      self.m.git.checkout(commit_id, force=force)

  def checkout_manifests(self, commit=None, is_staging=False,
                         checkout_internal=True, checkout_external=False):
    """Check out the manifest projects.

    Syncs the manifest projects into the workspace, at the appropriate revision.
    This is intended for builders that *only* need the manifest projects, not
    for builders that have other projects checked out as well.

    If |commit| is on an unpinned branch, there is no reasonable way to discern
    which revision of the external manifest is correct. The branch's copy of the
    external manifest is unbranched.  As such, the return will have an empty
    commit id, and the external manifest source tree may be dirty (mirrored
    manifest files will be copied from the internal manifest, but not
    committed.)

    Args:
      commit (GitilesCommit): The commit to use, or None for the default (from
        cros_infra_config.configure_builder)
      is_staging (bool): Whether this is staging.
      checkout_internal (bool): Whether to checkout the internal manifest.
        Defaults to true.
      checkout_external (bool): Whether to checkout the external manifest.
        Defaults to false.

    Returns:
      (GitilesCommit) The GitilesCommit to use for the external manifest.
    """
    if not checkout_internal and not checkout_external:
      # Nothing to do in this case!
      return None
    i_manifest = self.m.src_state.internal_manifest
    e_manifest = self.m.src_state.external_manifest
    working_manifest = i_manifest if checkout_internal else e_manifest
    commit = commit or self.m.src_state.gitiles_commit
    commit = commit if commit.host else working_manifest.as_gitiles_commit_proto

    if not checkout_internal:
      ext_commit = commit
    else:
      # Start building the external commit.  The id field will be set later, if we
      # can determine the one that matches the current checkout.
      ext_commit = e_manifest.as_gitiles_commit_proto
      ext_commit.ref = commit.ref
    branch = self._gitiles_branch(commit.ref)

    projects = self.m.src_state.manifest_projects
    if not checkout_internal:
      projects = [self.m.src_state.external_manifest.project]

    # Sync only the manifest projects, into the workspace directory.
    self.ensure_synced_cache(cache_path_override=self.workspace_path,
                             manifest_url=working_manifest.url,
                             is_staging=is_staging,
                             init_opts={'manifest_branch': branch or None
                                       }, sync_opts={'current_branch': False},
                             projects=projects)

    # If the commit uses a ref other than the manifest's ref, switch to that.
    # In general, this means that we will switch to either "snapshot", or to
    # some release branch (such as "release-R88-13597.B").
    if commit.ref != working_manifest.ref:
      self._manifest_branch = branch
    self._sync_target = {
        'call': 'checkout_manifests',
        'commit': MessageToDict(commit)
    }
    with self.m.context(cwd=working_manifest.path):
      # If we have an ID in the ref, make that HEAD.
      if commit.id:
        self.m.git.checkout(commit.id, force=True)

      # The branch we are on is either a snapshot branch (has a snapshot.xml
      # file), or it is an unpinned branch.
      snapshot_xml = working_manifest.path / 'snapshot.xml'
      self._branch_manifest_file = snapshot_xml
      if self._test_data.enabled and self._test_data.get(
          'snapshot_xml_exists', True):
        self.m.path.mock_add_paths(snapshot_xml)
      if not self.m.path.exists(snapshot_xml):
        if working_manifest.project == i_manifest.project:
          # If we're checking out both manifests and there is no snapshot.xml,
          # then there is no reasonable way to determine which revision of the
          # external manifest corresponds to our commit.  Copy the mirrored
          # files into the public manifest, and leave the tree dirty.
          for m_file in self.mirrored_manifest_files:
            i_path = i_manifest.path / m_file.src
            if m_file.src != 'external_full.xml':
              self.m.path.mock_add_paths(i_path)
            if self.m.path.exists(i_path):
              self.m.file.copy('copy {}'.format(m_file.src), i_path,
                               e_manifest.path / m_file.dest)

        # Generate a manifest file, and save the path.
        manifest_file = self.m.path.mkstemp(prefix='manifest')
        self.m.file.write_raw('write manifest file', manifest_file,
                              self.m.repo.manifest())
        self._branch_manifest_file = manifest_file
        return ext_commit

      # If we only have an external commit, there's no syncing to do. Return
      # early.
      if not checkout_internal:
        return ext_commit
      # If we have a snapshot.xml, checkout the corresponding public manifest
      # commit id, and update the external commit.
      ext_commit.id = self.get_external_snapshot_commit(working_manifest.path,
                                                        commit.id)
      if checkout_external:
        # Default to not checking out the external manifest.  It's possible that
        # GoB hasn't quite reconciled all of its copies, and it may not have
        # been included in the repo sync above, because of that timing.  The
        # orchestrator only needs to have it checked out if it is pushing
        # manifest_refs (such as snapshot-orchestrator).
        self.checkout_external_manifest(ext_commit.id)
      return ext_commit

  def checkout_branch(self, manifest_url, manifest_branch, projects=None,
                      init_opts=None, sync_opts=None, step_name=None):
    """Check out a branch of the current manifest.

    Note: If there are changes applied when this is called, repo will try to
    rebase them to the new branch.

    Args:
      * manifest_url (str): The manifest url.
      * manifest_branch (str): The branch to check out, such as
          'release-R86-13421.B'
      * projects (List[str]): Projects to limit the sync to, or None to sync
        all projects.
      * init_opts (dict): Extra keyword arguments to pass to 'repo.init'.
      * sync_opts (dict): Extra keyword arguments to pass to 'repo.sync'.
      * step_name (str): Name for the step, or None for default.
    """
    # Strip any leading "refs/heads/" from manifest_branch.
    manifest_branch = (
        manifest_branch[len('refs/heads/'):]
        if manifest_branch.startswith('refs/heads/') else manifest_branch)

    with self.m.context(cwd=self.workspace_path), \
        self.m.step.nest(step_name or
                         'checkout branch %s' % manifest_branch):
      self.m.easy.set_properties_step(manifest_branch=manifest_branch)
      my_init_opts = {}
      my_init_opts.update(init_opts or {})
      my_init_opts['manifest_branch'] = manifest_branch
      my_init_opts['projects'] = projects
      self.m.repo.init(manifest_url, **my_init_opts)

      my_sync_opts = copy.deepcopy(DEFAULT_CHECKOUT_SYNC_OPTS)
      my_sync_opts['jobs'] = self._determine_sync_jobs()
      my_sync_opts.update(sync_opts or {})
      my_sync_opts['projects'] = projects
      self.m.repo.sync(**my_sync_opts)
      self._manifest_branch = manifest_branch
      self._sync_target = {'call': 'checkout_branch', 'branch': manifest_branch}

      # TODO(crbug/1168649): Create partial manifest if projects is not None.
      if not projects:
        # The source is not dirty, we're just on a different branch.
        self.m.repo.ensure_pinned_manifest(
            projects=my_sync_opts.get('projects'))

  def checkout_tip_of_tree(self):
    """Check out the tip-of-tree in the workspace."""
    self._sync_target = {
        'call': 'checkout_tip_of_tree',
        'branch': self.m.src_state.internal_manifest.branch
    }
    self.ensure_synced_cache(manifest_branch_override='main')

  def fetch_snapshot_shas(
      self, count: int = 7 * 24 * 2,
      snapshot: Optional[bb_common_pb2.GitilesCommit] = None) -> List[str]:
    """Return snapshot SHAs for the manifest.

    Return SHAs for the most recent |count| commits in the manifest.  The
    default is to fetch 7 days worth of snapshots, based on (an assumed) 2
    snapshots per hour.

    Args:
      count: How many SHAs to return.
      snapshot: The latest snapshot to fetch, or None.

    Returns:
      The list of snapshot SHAs.
    """
    snapshot = snapshot or self.m.src_state.gitiles_commit
    manifest_dir = self.m.path.basename(snapshot.project)

    with self.m.context(cwd=self.workspace_path / manifest_dir):
      return self.m.git.fetch_refs(
          'https://{}/{}'.format(snapshot.host, snapshot.project), snapshot.id,
          count=count)

  def _sync_cached_dir(self, manifest_branch, retry_fetches=None, projects=None,
                       verbose=True, is_staging=False):
    """Sync to the chromiumos overlay.

    Args:
      retry_fetches (int): The number of times to retry retriable fetches.
      manifest_branch(str): Manifest branch to be used for init_opt.
      projects (List[str]): Projects to limit the sync to, or None to sync
        all projects.
      verbose (bool): Whether to produce verbose output.
      is_staging (bool): Flag to indicate staging environment
    """
    with self.m.step.nest('sync cached directory'):
      sync_path = self.cache_path
      manifest = self.m.src_state.internal_manifest

      init_opts = {'verbose': verbose, 'manifest_branch': manifest_branch}
      if is_staging:
        init_opts.update(STAGING_INIT_OPTS)
      sync_opts = copy.deepcopy(DEFAULT_CACHE_SYNC_OPTS)
      sync_opts.update({
          'verbose': verbose,
          'retry_fetches': retry_fetches,
          'jobs': self._determine_sync_jobs(),
      })

      if not self.m.repo.ensure_synced_checkout(
          sync_path, manifest.url, init_opts=init_opts, sync_opts=sync_opts,
          projects=projects):
        raise InfraFailure('failed to sync checkout')

      # Sync all branches of the internal manifest, so that we
      # can find branches.
      with self.m.context(cwd=self.cache_path / manifest.relpath):
        step_name = 'sync {} branches'.format(manifest.project)
        self.m.git.remote_update(step_name=step_name)

  @contextlib.contextmanager
  def checkout_overlays_context(self, mount_cache=True, disk_type='pd-ssd'):
    """Returns a context where overlays can be mounted.

    Args:
      mount_cache (bool): Whether to mount the chromiumos cache.  Default: True.
      disk_type (str): GCE disk type to use.  Default: pd-ssd
    """
    with self.m.overlayfs.cleanup_context():
      self._have_overlayfs_cleanup_context = True
      if mount_cache:
        branch = self.manifest_branch or 'main'
        lower_dir = self.m.gcloud.setup_cache_disk(
            cache_name=self._cache_name, branch=branch, disk_type=disk_type,
            recovery_snapshot=self._recovery_snapshot)
        self.m.overlayfs.mount(self._cache_name, lower_dir, self.cache_path,
                               persist=True)
        self.m.path.mock_add_paths(self.cache_path / '.repo')
        # Explicitly do not mount the workspace overlay at this time, to prevent
        # recipes from accidentally trashing their view of the source tree by
        # accessing it before ensure_synced_cache() is called.
      try:
        yield
      finally:
        self.m.easy.set_properties_step(source_sync_target=self._sync_target)
        self._have_overlayfs_cleanup_context = False

  def find_project_paths(self, project, branch, empty_ok=False):
    """Find the source paths for a given project in the workspace.

    Will only include multiple results if the same project,branch is mapped
    more than once in the manifest.

    Args:
      project (str): The project name to find a source path for.
      branch (str): The branch name to find a source path for.
      empty_ok (bool): If no paths are found, return an empty list rather than
        raising StepFailure

    Returns:
      list(str), The path values for the found project.
    """
    if not branch.startswith('refs/'):
      branch = 'refs/heads/%s' % branch
    paths = []
    with self.m.context(cwd=self.workspace_path):
      for project_info in self.m.repo.project_infos([project]):
        if project_info.branch == branch:
          paths.append(project_info.path)

      if not paths and not empty_ok:
        raise StepFailure('No path found for project %r branch %r' %
                          (project, branch))
      return paths

  def apply_gerrit_changes(self, gerrit_changes, include_files=False,
                           include_commit_info=False,
                           ignore_missing_projects=False,
                           test_output_data=None):
    """Apply GerritChanges to the workspace.

    Args:
      gerrit_changes (list[GerritChange]): list of gerrit changes to apply.
      include_files (bool): whether to include information about changed files.
      include_commit_info (bool): whether to include info about the commit.
      ignore_missing_projects (bool): Whether to ignore projects that are not
        in the source tree.  (For example, the builder uses the external
        manifest, but the CQ run includes private changes.)
      test_output_data (dict): Test output for gerrit-fetch-changes.

    Returns:
      List[PatchSet]: A list of commits from cherry-picked patch sets.
    """
    # We need files_info for the changes, so that we can make manifest changes
    # active.
    include_files = True
    self._is_source_dirty = True

    patch_sets = self.m.gerrit.fetch_patch_sets(
        gerrit_changes, include_commit_info=include_commit_info,
        include_files=include_files, test_output_data=test_output_data)

    self._apply_manifest_patch_sets(patch_sets)
    return self._apply_gerrit_patch_sets(
        patch_sets, ignore_missing_projects=ignore_missing_projects)

  def checkout_gerrit_change(self, change):
    """Check out a gerrit change using the gerrit refs/changes/... workflow.

      Differs from apply_changes in that the change is directly checked out,
      not cherry picked (so the patchset parent will be accurate). Used for
      things like tricium where line number matters.

    Args:
      change (GerritChange): Change to check out.
      name (string): Step name.  Default: "checkout gerrit change".
    """
    patch = self.m.gerrit.fetch_patch_sets([change])[0]
    project_path = self.find_project_paths(change.project, patch.branch)[0]
    with self.m.context(cwd=self.workspace_path / project_path):
      # Convert e.g. chromium-review.googlesource.com to e.g.
      # chromium.googlesource.com.
      remote_url = 'https://{}/{}'.format(
          change.host.replace('-review', ''), change.project)
      # Construct a ref like 'refs/changes/89/123456789/13'.
      change_ref = 'refs/changes/{}/{}/{}'.format(
          str(change.change)[-2:], change.change, change.patchset)
      self.m.git.fetch(remote_url, refs=[change_ref])
      self.m.git.checkout('FETCH_HEAD')

  def _apply_manifest_patch_sets(self, patch_sets):
    """Apply any manifest patch sets, and make them active.

    If there are any manifest patch sets, then apply them to the manifest, and
    make that the active manifest.  If we are on a pinned manifest, then switch
    to the unpinned version before applying patches.

    Args:
      patch_sets (list[PatchSet]): patch sets to consider.
    """

    # Partition the patches:
    # - build: patches to the build manifest (whatever it is), and then one of:
    #   - internal: patches to the internal manifest (build is external), or
    #   - external: patches to the external manifest (build is internal).
    # - manifest: union of the above.
    manifests, patches = self._partition_patches(patch_sets)
    if not patches.manifest:
      # There are no manifest changes. We are done.
      return

    external = manifests.build in manifests.extern
    with self.m.step.nest('patch manifest') as pres:
      # COIL: Allow manifest-internal and manifest to be on different branches
      # for tip-of-tree.
      # In reality, we could first checkout the internal (or build) manifest to
      # the correct branch, and then confirm that the branch of the external (or
      # build) manifest agrees with the patchesets.  However, they are *almost*
      # always the same, so we simply check the one case where they are expected
      # to be different.

      # Determine the branches for each of the (three) manifests, propagating
      # the build manifest to internal/external as appropriate.
      e_branches = {
          x.branch for x in (patches.build if external else patches.extern)
      }
      i_branches = {
          x.branch for x in (patches.intern if external else patches.build)
      }

      # If we have more than one branch, that is only valid if we are ToT for
      # both the internal and external manifests.
      branches = {x.branch for x in patches.manifest}
      if len(branches) > 1 and not (e_branches == {manifests.extern.branch} and
                                    i_branches == {manifests.intern.branch}):
        raise StepFailure('Cannot patch multiple branches: {}'.format(' '.join(
            sorted(branches))))

      # Determine the branch name(s) to use.  At least one if e_branches and/or
      # i_branches is non-empty, since there are manifest patches to apply.
      i_branch = i_branches.pop() if i_branches else None
      e_branch = e_branches.pop() if e_branches else None

      # If we have no patches to one of the manifests, then determine the
      # correct branch based on the other manifest's branch.
      i_branch = i_branch or (manifests.intern.branch if
                              e_branch == manifests.extern.branch else e_branch)
      e_branch = e_branch or (manifests.extern.branch if
                              i_branch == manifests.intern.branch else i_branch)
      branch = e_branch if external else i_branch

      branches_dict = {'manifest_branch': branch}
      branches_dict.update({
          'external_manifest_branch': e_branch,
          'internal_manifest_branch': i_branch,
      } if e_branch != i_branch else {})
      self.m.easy.set_properties_step(**branches_dict)

      # Now we know what branch we need to be on, and we need the manifest
      # repo(s) to be on that branch so that the CLs will apply.
      self.checkout_branch(manifests.build.url, branch, sync_opts={
          'current_branch': True,
          'detach': True
      })

      _changes_mirrored_file = lambda p, ext: any((
          n.dest if ext else n.src) in x.file_infos for x in p for n in self.
                                                  mirrored_manifest_files)

      # Changes to the external copy of mirrored files is an error.
      if _changes_mirrored_file(patches.build if external else patches.extern,
                                True):
        raise StepFailure(
            'Changes must be made in manifest-internal: {}'.format(', '.join(
                sorted(set(x.dest for x in self.mirrored_manifest_files)))))

      # If patches.intern is non-empty, then
      # 1. We do not have the internal manifest checked out, and
      # 2. We will need it so that we can apply manifest patches and potentially
      #    copy the file over to the external manifest.
      if patches.intern:
        with self.m.step.nest('sync internal manifest for patching'):
          # Fetch the internal manifest into its path.  Use the (synced) cache
          # as a reference, so that we do not use the network for this.
          self.m.git.clone(
              manifests.intern.url,
              target_path=manifests.intern.path,
              # TODO(b/266145294): Find out why it started failing when we pass
              # in reference.
              # reference=self.cache_path / manifests.intern.relpath,
              dissociate=True,
              timeout_sec=60 * 60)
          # Also, check out the correct branch of the internal manifest.
          with self.m.context(cwd=manifests.intern.path):
            self.m.git.checkout(i_branch)

      def _copy_mirrored_files():
        for m_file in self.mirrored_manifest_files:
          # Copy the file from internal to external manifest and commit
          i_path = manifests.intern.path / m_file.src
          e_path = manifests.extern.path / m_file.dest
          if m_file.src != 'external_full.xml':
            self.m.path.mock_add_paths(i_path)
          if self.m.path.exists(i_path):
            self.m.file.copy('copy {}'.format(m_file.src), i_path, e_path)
            with self.m.context(cwd=manifests.extern.path):
              self.m.git.add([e_path])
        with self.m.context(cwd=manifests.extern.path):
          res = self.m.git.commit(
              'Syncing with internal manifest.',
              stdout=self.m.raw_io.output_text(add_output_log=True),
              test_stdout='HEAD detached at 99caf97f', ok_ret=(0, 1))
          clean_msg = 'nothing to commit, working tree clean'
          if clean_msg in res.stdout.splitlines():
            return False
          if res.retcode:
            raise StepFailure('git commit', result=res)
          return True

      changed = self._apply_partitioned_manifest_patches(manifests, patches)
      if _changes_mirrored_file(patches.intern + patches.build, False):
        changed |= _copy_mirrored_files()
      if not changed:
        return

      # The manifest for this build has been patched.  We need to switch repo
      # to the newly patched tree.

      # The sequence of steps:
      # 1. Create a clone of the build manifest's repo outside of the workspace,
      #    with the refs changed so that it looks like the git repo found at
      #    build_manifest.url.
      # 2. Have repo sync the checkout in the workspace to the newly created
      #    manifest.
      # 3. Log a pinned version of the patched manifest.

      # The manifest file for repo init is 'default.xml' in the manifest
      # directory we are using for the build.
      default_file = manifests.build.path / 'default.xml'

      with self.m.context(
          cwd=manifests.build.path), self.m.step.nest('push manifest'):
        # 1. Remember head for both the build and external manifests, which may
        # be the same.
        # Do not update the gitiles commit, as path relevancy will try to
        # fetch this over the network.
        head = self.m.git.head_commit()
        with self.m.context(cwd=manifests.extern.path):
          e_head = self.m.git.head_commit()

        # 2. Create a clone of the manifest.
        # Force the the branch reference to point to HEAD.  We are likely
        # detached prior to this point.
        self.m.step('branch {}'.format(branch), ['git', 'checkout', branch])
        self.m.step('reset {}'.format(branch), ['git', 'reset', '--hard', head])

        # Create the clone.
        new_dir = self.m.path.mkdtemp('repo-overwrite-')
        self.m.step('clone',
                    ['git', 'clone', '--bare', '--shared', '.', new_dir])

        # Determine the correct name for the remote.
        step_test_data = lambda: self.m.raw_io.test_api.output_text(
            'cros' if external else 'internal-cros')
        remote = self.m.step('remote', ['git', 'remote'],
                             stdout=self.m.raw_io.output_text(),
                             step_test_data=step_test_data).stdout.strip()

        # Now push the manifest repo, and make the branches look as they
        # should for this to be build_manifest.url.
        self.m.step('push', [
            'git', 'push', new_dir,
            '+refs/remotes/{}/*:refs/heads/*'.format(remote),
            '+refs/heads/{branch}:refs/heads/{branch}'.format(branch=branch)
        ])

      # 3. Switch to the newly cloned mirror.  Tip-of-tree for for the original
      #    branch is the patched version of the |gitiles_commit| manifest.
      # This will finally use the patched manifest to fetch the tree.  Since
      # source repos may have changed, etc, we need to use force_sync=True.
      #
      # This also means that the build manifest directory will be reset to the
      # unpatched version, which we will fix momentarily.
      with self.m.step.nest('get patched manifest'):
        init_opts = {'manifest_branch': branch, 'manifest_name': default_file}
        sync_opts = copy.deepcopy(DEFAULT_CACHE_SYNC_OPTS)
        sync_opts.update({
            'manifest_name': default_file,
            'current_branch': True,
            'no_tags': False,
            'retry_fetches': 2,
            'detach': False,
            'force_sync': True,
            'no_manifest_update': True,
            'jobs': self._determine_sync_jobs()
        })

        manifest_url = 'file://%s' % new_dir
        if not self.m.repo.ensure_synced_checkout(
            self.workspace_path, manifest_url, init_opts=init_opts,
            sync_opts=sync_opts):
          raise InfraFailure('failed to sync checkout')

      # 4. Move the manifest directory (or both) back to the correct position.
      with self.m.step.nest('restore manifest patches'):
        with self.m.context(cwd=manifests.build.path):
          self.m.step('branch {}'.format(branch), ['git', 'checkout', branch])
          self.m.step('reset {}'.format(branch),
                      ['git', 'reset', '--hard', head])
        if not external:
          with self.m.context(cwd=manifests.extern.path):
            self.m.step('branch {}'.format(e_branch),
                        ['git', 'checkout', e_branch])
            self.m.step('reset {}'.format(e_branch),
                        ['git', 'reset', '--hard', e_head])

      # 5. Log a pinned version of the patched manifest.
      final = self.m.repo.manifest(pinned=True)
      self._pinned_manifest = final
      pres.logs['patched-manifest.xml'] = final

      self._sync_target = {
          'call': '_apply_manifest_patch_sets',
          'branch': branch
      }

  def _partition_patches(self, patch_sets):
    """Partition the manifest patches.

    Determine which patch sets apply to which manifests, and return namedtuples
    with the manifests and the different patch_sets to apply to them.

    A patch_set is only listed in the first manifest where we find it (build,
    external, internal), as well as in patches.manifest (which is the union of
    the other 3 fields.)

    Args:
      patch_sets (list[PatchSet]): The PatchSets for the build.

    Returns:
      (tuple):
      - manifests (namedtuple with 'build', 'extern', 'intern')
      - patches (namedtuple with 'build', 'extern', 'intern', and 'manifest')
    """

    _Manifests = namedtuple('_Manifests', ['build', 'extern', 'intern'])
    _Patches = namedtuple('_Patches', ['build', 'extern', 'intern', 'manifest'])
    b_man = self.m.src_state.build_manifest
    e_man = self.m.src_state.external_manifest
    i_man = self.m.src_state.internal_manifest

    b_patches, e_patches, i_patches = [], [], []
    for patch in patch_sets:
      if patch in b_man:
        b_patches.append(patch)
      elif patch in e_man:
        e_patches.append(patch)
      elif patch in i_man:
        i_patches.append(patch)
    man_patches = b_patches + e_patches + i_patches

    return (_Manifests(b_man, e_man, i_man),
            _Patches(b_patches, e_patches, i_patches, man_patches))

  def _apply_partitioned_manifest_patches(self, manifests, patches):
    """Apply manifest patchsets.

    Args:
      manifests (_Manifests): manifests tuple from _partition_patches.
      patches (_Patches): patches tuple from _partition_patches.

    Returns:
      (bool): whether the build manifest was changed.
    """

    _Commits = namedtuple('_Commits', ['build', 'extern', 'intern', 'all'])

    def _apply(patch_sets, project_path=None):
      """Helper to apply patch_sets.

      Args:
        patch_sets (list[PatchSets]): The list fo patches to apply to this
          manifest.
        project_path (str): The repo path, relative to the workspace_path.  Only
          use this if patching a repo that is not found in the manifest.
      """
      if patch_sets:
        name = '%s: apply gerrit patch sets' % patch_sets[0].project
        self._apply_gerrit_patch_sets(patch_sets, name=name,
                                      project_path=project_path)

    _apply(patches.build)
    _apply(patches.extern)
    _apply(patches.intern, project_path=manifests.intern.relpath)

    return bool(patches.build)

  def _apply_gerrit_patch_sets(self, patch_sets, ignore_missing_projects=False,
                               project_path=None, name=None):
    """Apply PatchSets to the workspace.

    Args:
      patch_sets (list[PatchSet]): The PatchSets to apply.
      ignore_missing_projects (bool): Whether to ignore projects that are not
        in the source tree.  (For example, the builder uses the external
        manifest, but the CQ run includes private changes.) Note that for a
        given PatchSet if project is in the manifest but the branch is not, the
        PatchSet will still be ignored.
      project_path (str): The path to use when applying the patch, or none to
        use find_project_paths.
      name (str): The name for the step, or None.

    Returns:
      List[PatchSet]: The list of cherry-picked patch sets. Not all patch sets
        may be applied if ignore_missing_projects is true.
    """
    with self.m.step.nest(name or 'apply gerrit patch sets') as pres:
      if ignore_missing_projects:
        # The branch returned by repo.project_infos contains 'refs/heads/', but
        # the branch in patch_sets does not. Strip the 'refs/heads/' here. If
        # there is no branch in the ProjectInfo use the default branch.
        synced_projects = set((p.name, p.branch.replace('refs/heads/', '') if p
                               .branch else self.m.src_state.default_branch)
                              for p in self.m.repo.project_infos())

        # Only retain patches to synced projects.  Mark as discarded any patches
        # to other projects, unless they have already been applied (manifest
        # patches). Note that we check if the specific branch is synced for the
        # project.
        discard = [
            p for p in patch_sets
            if (p.project, p.branch) not in synced_projects and
            p.display_id not in self._applied_patches
        ]
        patch_sets = [
            p for p in patch_sets if (p.project, p.branch) in synced_projects
        ]
        if discard:
          pres.step_text = 'Discarded changes: {}'.format(', '.join(
              p.display_id for p in discard))

      for patch in patch_sets:
        if patch.display_id not in self._applied_patches:
          project_paths = ([project_path] if project_path else
                           self.find_project_paths(patch.project, patch.branch))
          for path in project_paths:
            self.apply_patch_set(patch, path)
      return patch_sets

  def apply_patch_set(self, patch, project_path, is_abs_path=False):
    """Apply a PatchSet to the git repo in ${CWD}.

    Args:
      patch (PatchSet): The PatchSet to apply.
      project_path (str): The path in which to apply the change.
      is_abs_path (bool): Whether the project path is an absolute path. The
        default is False meaning the project_path is relative to the workspace.
    """
    path = project_path if is_abs_path else self.workspace_path.joinpath(
        project_path)
    with self.m.context(cwd=path):
      commit = self.m.git.fetch_ref(patch.git_fetch_url, patch.git_fetch_ref)
      if self.git_strategy == GitStrategy.CHERRY_PICK and not self.m.git.is_merge_commit(
          commit):
        cherry_picked = self.m.git.cherry_pick_silent_fail(
            commit, infra_step=False)
        self.git_strategy = GitStrategy.CHERRY_PICK
        if not cherry_picked:
          self.m.git.cherry_pick_abort()
          presentation = self.m.step.active_result.presentation
          presentation.status = self.m.step.SUCCESS
          presentation.step_text = 'cherry-pick failed. will try merge instead'
          self.m.git.merge(commit, 'merge gerrit changes', infra_step=False)
          self.git_strategy = GitStrategy.MERGE
      else:
        self.git_strategy = GitStrategy.MERGE
        try:
          self.m.git.merge(commit, 'merge gerrit changes', infra_step=False)
        except StepFailure:
          self.m.git.merge_abort()
          raise StepFailure('merge %s failed. Aborting.' % commit)  # pylint: disable=raise-missing-from
      self.m.easy.set_properties_step(
          cros_source_git_strategy=self.git_strategy)
      self._applied_patches[patch.display_id].append(patch)

  retry_timeouts = lambda e: getattr(e, 'had_timeout', False)

  def sync_checkout(self, commit=None, manifest_url=None, **kwargs):
    """Sync a checkout to the appropriate manifest.

      If the module properties contain the `sync_to_manifest` field, that will
      be used. Otherwise the given commit/manifest_url will be used.

      Args:
        commit (GitilesCommit): The gitiles_commit to sync to.  Default: commit
          saved in cros_infra_config.configure_builder().
        manifest_url: URL of manifest repo.  Default: internal manifest
    """
    self._clear_applied_patches_list()
    if self._sync_to_manifest and self._sync_to_manifest.manifest_gs_path:
      self.m.cros_source.sync_to_pinned_manifest(
          manifest_gs_path=self._sync_to_manifest.manifest_gs_path, **kwargs)
    elif self._sync_to_manifest and self._sync_to_manifest.manifest_repo_url:
      self.m.cros_source.sync_to_pinned_manifest(
          self._sync_to_manifest.manifest_repo_url,
          self._sync_to_manifest.branch, self._sync_to_manifest.manifest_file,
          **kwargs)
    else:
      self.m.cros_source.sync_to_gitiles_commit(commit, manifest_url, **kwargs)

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=1),
                     condition=retry_timeouts)
  def sync_to_pinned_manifest(self, manifest_url='', manifest_branch='',
                              manifest_path='', manifest_gs_path='', **kwargs):
    """Sync a checkout to the specified [pinned] manifest.

      The manifest will be downloaded directly from the source using gitiles.

    Args:
      manifest_url (string): URL of the project the manifest is in, e.g.
        https://chrome-internal.googlesource.com/chromeos/manifest-versions
      manifest_branch (string): Branch of repository to get manifest from,
        e.g. 'main'.
      manifest_path (string): Path (relative to repository root) of manifest
        file, e.g. buildspecs/91/13818.0.0.xml.
      manifest_gs_path (string): GS Path of manifest, e.g.
        gs://chromeos-manifest-versions/release/91/13818.0.0.xml.
        Takes precendence over manifest_url/branch/path.
    """
    with self.m.step.nest('sync to specified manifest'), self.m.context(
        cwd=self.workspace_path):
      valid_params = (manifest_url and manifest_branch and
                      manifest_path) or manifest_gs_path
      if not valid_params:
        raise StepFailure(
            'either need all of manifest_url/manifest_branch/manifest_path or manifest_gs_path'
        )

      testdata = '<manifest></manifest>'
      if not manifest_gs_path:
        # Check that the manifest_url is allowed.
        if manifest_url not in ALLOWED_MANIFEST_SOURCES:
          raise StepFailure('manifest_url ({}) was not one of {}'.format(
              manifest_url, ','.join(ALLOWED_MANIFEST_SOURCES)))

        step_test_data = lambda: self.m.depot_gitiles.test_api.make_encoded_file(
            testdata)
        manifest_xml = self.m.depot_gitiles.download_file(
            manifest_url, manifest_path, manifest_branch,
            step_test_data=step_test_data, accept_statuses=[200],
            timeout=self.test_api.gitiles_timeout_seconds)

        self._sync_target = {
            'call': 'sync_to_manifest',
            'manifest_url': manifest_url,
            'manifest_path': manifest_path,
            'manifest_branch': manifest_branch,
        }
      else:
        manifest_xml = self.m.gsutil.cat(
            manifest_gs_path, stdout=self.m.raw_io.output_text(),
            step_test_data=lambda: self.m.raw_io.test_api.stream_output_text(
                testdata)).stdout.strip()
        self._sync_target = {
            'call': 'sync_to_manifest',
            'manifest_gs_path': manifest_gs_path
        }

      manifest_relpath = self.m.repo.create_tmp_manifest(manifest_xml)
      init_opts = {
          'manifest_name': manifest_relpath,
          'manifest_branch': manifest_branch,
      }
      sync_opts = {
          'detach': True,
          'optimized_fetch': True,
          'retry_fetches': 8,
          'force_sync': True,
          'manifest_name': manifest_relpath,
      }
      sync_opts.update(kwargs)

      if not self.m.repo.ensure_synced_checkout(
          self.m.src_state.workspace_path, manifest_url, init_opts=init_opts,
          sync_opts=sync_opts):
        raise InfraFailure('failed to sync checkout')  #pragma: no cover

      self._pinned_manifest = (
          self.m.repo.ensure_pinned_manifest(test_data='') or manifest_xml)

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=1),
                     condition=retry_timeouts)
  def sync_to_gitiles_commit(self, gitiles_commit, manifest_url=None, **kwargs):
    """Sync a checkout to the specified gitiles commit.

      Will first attempt to sync to snapshot.xml, then default.xml.

    Args:
      gitiles_commit (GitilesCommit): commit to sync to
      manifest_url: URL of manifest repo.  Default: internal manifest
      kwargs (dict): additional args for repo.sync_manifest.
    """
    manifest_url = manifest_url or self.m.src_state.internal_manifest.url
    with self.m.step.nest('sync to gitiles commit'), self.m.context(
        cwd=self.workspace_path, infra_steps=True):
      self._manifest_branch = self._gitiles_branch(gitiles_commit.ref)
      self._sync_target = {
          'call': 'sync_snapshot',
          'commit': MessageToDict(gitiles_commit),
      }
      projects = kwargs.get('projects', None)
      snapshot_xml = self._get_manifest(gitiles_commit, projects=projects)
      # Force_sync to ensure that we get the snapshot that we want.
      sync_opts = {'detach': True}
      sync_opts.update(DEFAULT_CHECKOUT_SYNC_OPTS)
      sync_opts['jobs'] = self._determine_sync_jobs()
      if gitiles_commit.ref not in ('refs/heads/snapshot', 'refs/heads/main',
                                    'refs/heads/staging-snapshot'):
        # TODO(b/186770501): Changing branches can take a while.
        sync_opts['timeout'] = 7200
      sync_opts.update(kwargs)
      try:
        self.m.repo.sync_manifest(manifest_url, manifest_data=snapshot_xml,
                                  **sync_opts)
      except StepFailure:
        sync_opts['force_remove_dirty'] = True
        self.m.easy.set_properties_step(force_remove_dirty=True)
        self.m.repo.sync_manifest(manifest_url, manifest_data=snapshot_xml,
                                  **sync_opts)
      # TODO(crbug/1168649): Create partial manifest if projects is not None.
      if not projects:
        # Get the pinned manifest from repo.  If that returns None, then we
        # already have the pinned manifest in snapshot_xml.
        self._pinned_manifest = (
            self.m.repo.ensure_pinned_manifest(projects=projects, test_data='')
            or snapshot_xml)

  def _get_manifest(self, gitiles_commit, projects=None):
    """Returns the manifest to use.

    Returns the manifest to use. If a custom snapshot has been provided
    via an input property, that will be used. Otherwise it will fall back
    to the typical syncing to the gitiles_commit.
    """
    if self._snapshot_cas:
      return self._get_snapshot_from_cas()
    return self._get_manifest_from_gitiles(gitiles_commit, projects=projects)

  def _get_snapshot_from_cas(self):
    """Returns the snapshot to use from cas"""
    sc = self._snapshot_cas
    snapshot_dir = self.m.path.mkdtemp('snapshot')
    self.m.cas.download('download snapshot.xml from cas', digest=sc.digest,
                        output_dir=snapshot_dir)
    return self.m.file.read_text('read snapshot.xml',
                                 snapshot_dir / 'snapshot.xml',
                                 test_data='<manifest></manifest>')

  def _get_manifest_from_gitiles(self, gitiles_commit, projects=None):
    """Returns the manifest to use from gitiles.

      First looks for snapshot.xml in the appropriate directory.
      If snapshot.xml does not exist, returns an unpinned manifest
      generated from default.xml.

    Args:
    gitiles_commit (GitilesCommit): Commit to use.
    projects (List[str]): Projects to use if a sync is necessary,
      or None to sync all projects.
    """
    gitiles_url = 'https://%s/%s' % (gitiles_commit.host,
                                     gitiles_commit.project)

    testdata = '<manifest></manifest>'
    step_test_data = lambda: self.m.depot_gitiles.test_api.make_encoded_file(
        testdata)

    data = self.m.depot_gitiles.download_file(
        gitiles_url, 'snapshot.xml', branch=gitiles_commit.id,
        step_test_data=step_test_data, accept_statuses=[200, 404],
        timeout=self.test_api.gitiles_timeout_seconds)
    if data:
      return data

    # If there is no snapshot.xml, then we need to go to the appropriate
    # branch of the appropriate manifest and generate the manifest.
    manifest = self.m.src_state.gitiles_commit_to_manifest(gitiles_commit)
    with self.m.context(cwd=manifest.path):
      self.checkout_branch(manifest.url, gitiles_commit.ref, projects=projects)
      self.m.git.fetch(manifest.remote, [gitiles_commit.id])
      self.m.git.checkout(gitiles_commit.id, force=True)
      snapshot_path = manifest.path / 'snapshot.xml'
      # If the branch is pinned, use snapshot.xml, otherwise generate an
      # unpinned manifest and return that.
      return (self.m.file.read_raw('read local snapshot.xml', snapshot_path,
                                   test_data=testdata)
              if self.m.path.exists(snapshot_path) else self.m.repo.manifest(
                  manifest_file=manifest.path / 'default.xml', pinned=False))

  def uprev_packages(self, workspace_path=None, build_targets=None,
                     timeout_sec=(10 * 60), name='uprev packages'):
    """Uprev packages.

    Args:
      workspace_path (Path): Path to the workspace checkout.
      build_targets (list[BuildTarget]): List of build_targets whose packages.
        should be uprevved, or None for all build_targets.
      timeout_sec (int): Step timeout (in seconds).  Default: 10 minutes.
      name (string): Name for step.

    Returns:
      UprevPackagesResponse
    """
    with self.m.step.nest(name), self.m.context(cwd=workspace_path):
      # Produces file changes if an uprev is possible.
      return self.m.cros_build_api.PackageService.Uprev(
          UprevPackagesRequest(build_targets=build_targets,
                               overlay_type=OVERLAYTYPE_BOTH),
          timeout=timeout_sec)

  def push_uprev(self, uprev_response, dry_run, commit_only=False,
                 is_staging=False, discard_unpushed_changes=False):
    """Commit and push any upreved packages to its remote.

    Args:
      uprev_response (list[PushUprevRequest]): Named tuple containing the
        modified ebuild and associated message subject.
      dry_run (bool): Dry run git push or not.
      commit_only (bool): Whether to skip the push step.
      is_staging (bool): Whether the builder is a staging builder.
      discard_unpushed_changes (bool): Whether to discard unpushed commits when
        commit_only is True, necessary for release builders where we need
        buildspecs to contain valid commits.

    Return:
      all_uprevs_passed (bool): True if all uprevs succeeded,
                                False if ANY failed.
    """
    with self.m.step.nest('push uprevs') as push_uprevs_pres:

      # Create list of modified files, index by their repository
      modified_ebuilds_by_repository = {}

      # Cycle through modified ebuilds
      with self.m.step.nest('retrieve project information'):
        for item in uprev_response:
          # TODO(b/192099206): When recipes moves to python3, this will be
          # cleaner with default values
          path = str(item.modified_files[0])
          # self.m.assertions.assertEqual(item, 0)
          with self.m.context(
              cwd=self.m.path.abs_to_path(self.m.path.dirname(path))):
            repository = self.m.git.repository_root(
                step_name='repo for {}'.format(
                    self.m.path.relpath(path, self.m.src_state.workspace_path)))

            if repository in modified_ebuilds_by_repository:
              modified_ebuilds_by_repository[repository].modified_files.append(
                  path)
            else:
              modified_ebuilds_by_repository[
                  repository] = self.PushUprevRequest([path],
                                                      item.message_subject)

      with self.m.step.nest('commit uprevs'):
        # Cycle through the modifed ebuild and push the change.
        for repository, requests in sorted(
            modified_ebuilds_by_repository.items()):
          repo_name = self.m.path.relpath(repository,
                                          self.m.src_state.workspace_path)
          with self.m.context(cwd=self.m.path.abs_to_path(repository)):
            with self.m.step.nest(
                'commit uprev changes in {}'.format(repo_name)) as commit_pres:
              self.m.git.add(requests.modified_files)
              message = '\n'.join([
                  requests.message_subject,
                  '',
                  'Cr-Build-Url: {}'.format(self.m.buildbucket.build_url()),
                  'Cr-Automation-Id: cros_source/push_uprevs',
              ]) + '\n'
              self.m.git.commit(message, files=requests.modified_files)
              commit_pres.logs['ebuilds'] = requests.modified_files

            if commit_only and discard_unpushed_changes:
              self.m.step('discard unpushed uncommitted uprev commit',
                          ['git', 'reset', '--hard', 'HEAD~'])

      # If we do not want to push, return that the call has passed.
      if commit_only:
        return True

      all_uprevs_passed = True
      failed_uprevs = []
      passed_uprevs = []
      for repository, requests in sorted(
          modified_ebuilds_by_repository.items()):
        repo_name = self.m.path.relpath(repository,
                                        self.m.src_state.workspace_path)
        with self.m.step.nest('push to {}'.format(repo_name)) as push_pres:
          push_pres.logs['repo'] = repository
          with self.m.context(cwd=self.m.path.abs_to_path(repository)):
            # Filter to ebuilds that exist. In particular, we need to exclude
            # the version of the ebuild from prior to the uprev.
            existing_ebuilds = []
            for ebuild in requests.modified_files:
              self.m.path.mock_add_paths(ebuild)
              if self.m.path.exists(ebuild):
                existing_ebuilds.append(ebuild)

            projects = self.m.repo.project_infos(projects=existing_ebuilds)
            # The list of projects should be checked to see if all elements
            # are equivalent. This check is temporarily removed because
            # Annealing is broken, and length isn't the right thing to check.
            # assert len(projects) == 1, \
            #     'expected 1 project, got: %r' % projects
            push_pres.logs['projects'] = str(projects)
            project = projects[0]
            push_pres.logs['project chosen'] = str(project)
            step_name = 'git push {}'.format(repo_name)
            branch = project.branch_name
            namespace = 'heads'
            if is_staging:
              branch = 'staging-infra-{}'.format(branch)
            refspec = 'HEAD:refs/{}/{}'.format(namespace, branch)

            try:
              self.m.git.push(project.remote, refspec, dry_run=dry_run,
                              capture_stdout=True, retry=False, name=step_name)
              passed_uprevs.append(repo_name)
            except StepFailure as ex:
              self.m.step.active_result.presentation.logs['exception'] = (
                  ex.result.stdout.splitlines())
              git_flags = self._check_push_exception(ex)
              if git_flags.no_change:
                self.m.step.active_result.presentation.status = \
                  self.m.step.SUCCESS
              elif git_flags.merge_required:
                # try resolving the issue three times before failing
                self.m.step.active_result.presentation.status = \
                  self.m.step.WARNING
                with self.m.step.nest('retry uprev to {}'.format(repo_name)):
                  for index in range(3):
                    with self.m.git.head_context():
                      try:
                        self._uprev_retry(project, dry_run, step_name, branch,
                                          is_staging, namespace)
                        passed_uprevs.append(repo_name)
                        break
                      except StepFailure:
                        if index == 2:
                          failed_uprevs.append(repo_name)
                          all_uprevs_passed = False
              else:
                failed_uprevs.append(repo_name)
                all_uprevs_passed = False

      # Log failures and successes
      if all_uprevs_passed:
        # If they all eventually succeeded, the step was successful.
        push_uprevs_pres.status = self.m.step.SUCCESS
      else:
        push_uprevs_pres.logs['Failed Uprevs'] = sorted(failed_uprevs)
      push_uprevs_pres.logs['Passed Uprevs'] = sorted(passed_uprevs)

      return all_uprevs_passed

  def _check_push_exception(self, exception):
    """Parse stdout in push exception

    When the push during an uprev fails we need to parse the output to
    determine what out next steps will be.

    Args:
      exception(StepFailure): step failure encounted during git push

    Returns(FailureFlags):
      no_change(bool): git push failed due to no files changed.
      merge_required(bool): fetch and merge of remote required.
    """
    FailureFlags = namedtuple(
        'FailureFlags',
        ['no_change', 'merge_required'],
    )
    no_change = merge_required = False
    for line in exception.result.stdout.splitlines():
      no_change |= bool(re.search(r'\(no new changes\)', line))
      merge_required |= bool(
          re.search(r'\(fetch first\)', line) or
          re.search(r'\(non-fast-forward\)', line))
    return FailureFlags(no_change, merge_required)

  def _uprev_retry(self, project, dry_run, step_name, branch, is_staging,
                   namespace):
    """Retry the uprev push

    LUCI CQ may push changes while we are upreving. This retry process will
    attempt to bypass those collisions by fetching, merging, and then repushing
    the uprevs.

    Args:
      project(ProjectInfo): Information desribing the repo.
      dry_run(bool): Dry run the git push.
      step_name(string): Step name overide for the git push.
      branch(string): Branch name to push to.
      is_staging(bool): If annealing is running in staging or not.
      namespace(string): The namespace for the ref ('heads' or 'staging-infra').
    """
    current_branch = self.m.git.current_branch() or self.m.git.head_commit()
    ref = 'refs/{}/{}'.format(namespace, branch)
    self.m.git.fetch(project.remote, [ref])
    if is_staging:
      # Ignore all the changes on the ref, since they have been done on
      # ToT since then.
      self.m.git.merge(
          'FETCH_HEAD',
          'Resolve uprev conflict\n',
          '--strategy=ours',
      )
    else:
      self.m.git.checkout('FETCH_HEAD')
      self.m.git.merge(current_branch, 'Resolve uprev conflict\n')
    self.m.git.push(project.remote, 'HEAD:{}'.format(ref), dry_run=dry_run,
                    capture_stdout=True, retry=False, name=step_name)

  def related_changes_to_apply(
      self, gerrit_changes: List[bb_common_pb2.GerritChange],
      all_related_changes: OrderedDict_type[str, Dict[str, Any]]
  ) -> OrderedDict_type[str, Dict[str, Any]]:
    """Based on what is already included, figure out which related changes are implicitly depended on by gerrit_changes.

    Note that only related changes that precede the changes in gerrit_changes
    will be applied. Related changes that follow a change in gerrit_changes
    will not be applied unless explicitly included.

    Args:
      gerrit_changes: Changes to apply for the builder.
      all_related_changes: All related changes for all gerrit_changes. May
        include duplicates.

    Returns:
      De-duplicated changes that are implicitly depended on by gerrit_changes
        in a relation chain, but not already included in gerrit_changes.
    """
    with self.m.step.nest('evaluating related changes') as pres:
      pres.logs['gerrit changes'] = str(gerrit_changes)
      log = ''
      already_applied_ids = set()
      related_changes_to_apply = OrderedDict()
      for change_id, related in all_related_changes.items():
        already_applied_ids.add(change_id)
        to_apply = []
        # Related changes are listed from newest to oldest, but we want to
        # start with oldest.
        related.reverse()
        for rel in related:
          change_num = rel['_change_number']
          if change_num not in already_applied_ids:
            to_apply.append(rel)
            already_applied_ids.add(change_num)
          else:
            log += f'Skipping {rel} which is already included.'
          # Once we reach the change that's actually included with the builder,
          # stop traversing related changes so we include related changes lower
          # in a stack, but not the change itself or related changes higher in
          # a stack (unless explicitly included).
          if change_id == rel['_change_number']:
            break
        if to_apply:
          related_changes_to_apply[change_id] = to_apply
      pres.logs['skips'] = log
      pres.logs['related changes to apply'] = str(related_changes_to_apply)
      return related_changes_to_apply
