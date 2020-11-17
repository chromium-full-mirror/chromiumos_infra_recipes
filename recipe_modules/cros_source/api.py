# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS source."""

import contextlib
import json

from collections import defaultdict, namedtuple

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from recipe_engine.recipe_api import RecipeApi, StepFailure
from recipe_engine.util import exponential_retry

ProjectCommit = namedtuple('ProjectCommit', ['path', 'commit_id', 'patch_set'])

# Default sync options for syncing the named cache.
DEFAULT_CACHE_SYNC_OPTS = dict(current_branch=True, detach=True,
                               force_sync=True, jobs=8, no_tags=True,
                               optimized_fetch=True, retry_fetches=8,
                               timeout=3600)

STAGING_INIT_OPTS = dict(repo_branch='main')

# Default options for checking out a branch.
DEFAULT_CHECKOUT_SYNC_OPTS = dict(jobs=8, optimized_fetch=True, timeout=3600,
                                  force_sync=True, retry_fetches=8)


class CrosSourceApi(RecipeApi):
  """A module for CrOS-specific source steps."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosSourceApi, self).__init__(*args, **kwargs)
    self._snapshot_isolate = (
        properties.snapshot_isolate
        if properties.HasField('snapshot_isolate') else None)
    self._is_source_dirty = bool(self._snapshot_isolate)
    self._enable_custom_overlays = properties.enable_custom_overlays
    self._make_manifest_changes_active = properties.make_manifest_changes_active
    # The currently active branch of the manifest.  Empty unless we switched
    # branches.
    self._manifest_branch = ''
    self._pinned_manifest = None
    self._applied_patches = defaultdict(list)

  def initialize(self):
    """Initialization that follows all module loading."""
    self._enable_custom_overlays |= (
        'chromeos.cros_source.enable_custom_overlays' in
        self.m.cros_infra_config.experiments)
    self._make_manifest_changes_active |= (
        'chromeos.cros_source.make_manifest_changes_active' in
        self.m.cros_infra_config.experiments)

  @property
  def pinned_manifest(self):
    self._pinned_manifest = (
        self._pinned_manifest or self.m.repo.manifest(pinned=True))
    return self._pinned_manifest

  @property
  def manifest_branch(self):
    """Returns any non-default manifest branch that is checked out."""
    return self._manifest_branch

  @property
  def is_source_dirty(self):
    """Returns whether the source is dirty.

    Returns whether the source is dirty. The source is dirty if it was checked
    out to a custom snapshot from isolate or has had patches applied or has
    been moved to a branch.
    """
    return self._is_source_dirty

  @property
  def preload_path(self):
    """The cached image checkout path.

    This is the cached version of source that is included in the base image of
    the bot, used as an initial reference path.
    """
    return '/preload/chromeos'

  @property
  def cache_path(self):
    """The cached checkout path.

    This is the cached version of source (the internal manifest checkout),
    usually updated once at the beginning of a build and then mounted into the
    master and/or workspace paths.
    """
    return self.m.path['cache'].join('chromiumos')

  @property
  def workspace_path(self):
    """The "workspace" checkout path.

    This is where the build is processed. It will contain the target base
    checkout and any modifications made by the build.
    """
    return self.m.src_state.workspace_path

  @property
  def snapshot_isolated_hash(self):
    """Returns the snapshot isolate hash in use or None."""
    return (self._snapshot_isolate.isolated_hash
            if self._snapshot_isolate else None)

  def _validate_args(self, manifest_url, local_manifest, groups, cache_path,
                     manifest_branch):
    """Ensure the args to ensure_synced_cache are to a supported configuration.

    Supported configurations include:
      - INTERNAL: Sync the internal manifest to self.cache_path.
      - CUSTOM: Sync any manifest to any path other than
        self.cache_path.

    Args:
      manifest_url (str): Manifest URL for 'repo.init`.
      local_manifest (repo.LocalManifest): Local manifest to add or None if not
        syncing a local manifest.
      groups (list[str]): List of manifest groups to checkout.
      cache_path (Path): Path to sync into. If None, the cache_path
        property is used.
      manifest_branch (str): The branch to check out, such as
        'release-R86-13421.B'.
    Returns:
      If the configuration is supported, the type of configuration.
    """
    if cache_path == self.cache_path:
      if (manifest_url != self.m.src_state.internal_manifest.url or
          local_manifest or groups or manifest_branch):
        raise ValueError('Only the internal manifest on the default branch can'
                         'be synced to the chromiumos cache path.')
      return 'INTERNAL'
    return 'CUSTOM'

  def ensure_synced_cache(self, manifest_url=None, init_opts=None,
                          sync_opts=None, cache_path_override=None,
                          is_staging=False, projects=None, gitiles_commit=None):
    """Ensure the configured repo cache exists and is synced.

    Args:
      * manifest_url (str): Manifest URL for 'repo.init`.
      * init_opts (dict): Extra keyword arguments to pass to 'repo.init'.
      * sync_opts (dict): Extra keyword arguments to pass to 'repo.sync'.
      * cache_path_override (Path): Path to sync into. If None, the cache_path
      property is used.
      * is_staging (bool): Flag to indicate canary staging environment
      * projects (List[str]): Projects to limit the sync to, or None to sync
      all projects.
      * gitiles_commit (GitilesCommit): The gitiles_commit, or None to use the
      current value.
    """
    # There are a few things we want to make sure are set globally for git.
    # Do them here to help protect the named cache from corruption due to
    # off-branch objects being removed.
    # Disable automatic garbage collection.  See https://crbug.com/1137935.
    self.m.git.set_global_config(['gc.auto', '0'])
    # Disable packRefs before doing merges. See https://crbug.com/1057878.
    self.m.git.set_global_config(['gc.packRefs', 'false'])

    if self._enable_custom_overlays:
      self.m.overlayfs.mount('chromiumos', self.preload_path, self.cache_path,
                             persist=True)
      self.m.path.mock_add_paths(self.cache_path.join('.repo'))
      self.m.overlayfs.mount('workspace', self.cache_path, self.workspace_path)
      self.m.path.mock_add_paths(self.workspace_path.join('.repo'))

    cache_path = cache_path_override or self.cache_path
    manifest_url = manifest_url or self.m.src_state.internal_manifest.url

    gitiles_commit = gitiles_commit or self.m.src_state.gitiles_commit
    gitiles_commit = (
        gitiles_commit if gitiles_commit.host else
        self.m.src_state.internal_manifest.as_gitiles_commit_proto)
    init_opts = init_opts or {}
    if is_staging:
      init_opts.update(STAGING_INIT_OPTS)
    sync_opts = dict(DEFAULT_CACHE_SYNC_OPTS, **(sync_opts or {}))
    local_manifest = init_opts.get('local_manifest')
    groups = init_opts.get('groups')
    verbose = init_opts.get('verbose')
    manifest_branch = init_opts.get('manifest_branch')
    retry_fetches = sync_opts.get('retry_fetches')

    configuration = self._validate_args(manifest_url, local_manifest, groups,
                                        cache_path, manifest_branch)
    if configuration == 'INTERNAL':
      self._sync_cached_dir(retry_fetches, projects, verbose, external=False,
                            is_staging=is_staging)
    else:
      self.m.repo.ensure_synced_checkout(cache_path, manifest_url,
                                         init_opts=init_opts,
                                         sync_opts=sync_opts, projects=projects)
      # Sync all branches of the build manifest, so that we can find branches.
      # If groups were specified, then the manifest project is probably not
      # present, so don't bother.
      if not groups:
        with self.m.step.nest('sync manifest branches'):
          sync_opts.update(current_branch=False,
                           projects=[self.m.src_state.build_manifest.project])
          with self.m.context(cwd=cache_path):
            self.m.repo.sync(**sync_opts)

  def checkout_branch(self, manifest_url, manifest_branch, init_opts=None,
                      sync_opts=None, step_name=None):
    """Check out a branch of the current manifest.

    Note: If there are changes applied when this is called, repo will try to
    rebase them to the new branch.

    Args:
      * manifest_branch (str): The branch to check out, such as
          'release-R86-13421.B'
      * manifest_url (str): The manifest url.
      * init_opts (dict): Extra keyword arguments to pass to 'repo.init'.
      * sync_opts (dict): Extra keyword arguments to pass to 'repo.sync'.
      * step_name (str): Name for the step, or None for default.
    """
    with self.m.context(cwd=self.workspace_path), \
        self.m.step.nest(step_name or
                         'checkout branch %s' % manifest_branch) as pres:
      my_init_opts = {}
      my_init_opts.update(init_opts or {})
      my_init_opts['manifest_branch'] = manifest_branch
      self.m.repo.init(manifest_url, **my_init_opts)

      my_sync_opts = dict(**DEFAULT_CHECKOUT_SYNC_OPTS)
      my_sync_opts.update(sync_opts or {})
      self.m.repo.sync(**my_sync_opts)
      self._manifest_branch = manifest_branch
      # The source is not dirty, we're just on a different branch.
      self.m.repo.ensure_pinned_manifest(projects=my_sync_opts.get('projects'))

  def fetch_snapshot_shas(self, count=7 * 24 * 2):
    """Return snapshot SHAs for the manifest.

    Return SHAs for the most recent |count| commits in the manifest.  The
    default is to fetch 7 days worth of snapshots, based on (an assumed) 2
    snapshots per hour.

    Args:
      * count (int): How many SHAs to return.

    Returns:
      (list[str]) The list of snapshot SHAs.
    """
    snapshot = self.m.src_state.gitiles_commit
    manifest_dir = self.m.path.basename(snapshot.project)

    with self.m.context(cwd=self.workspace_path.join(manifest_dir)):
      return self.m.git.fetch_refs(
          'https://{}/{}'.format(snapshot.host, snapshot.project), snapshot.id,
          count=count)

  def _sync_cached_dir(self, retry_fetches=None, projects=None, verbose=False,
                       external=False, is_staging=False):
    """Sync to the chromiumos overlay.

    Args:
      retry_fetches (int): The number of times to retry retriable fetches.
      projects (List[str]): Projects to limit the sync to, or None to sync
        all projects.
      verbose (bool): Whether to produce verbose output.
      external (bool): Flag to indiciate syncing to the external manifest.
      is_staging (bool): Flag to indicate staging environment
    """
    sync_path = self.cache_path
    manifest = self.m.src_state.internal_manifest

    init_opts = dict(verbose=verbose)
    if is_staging:
      init_opts.update(STAGING_INIT_OPTS)
    sync_opts = dict(DEFAULT_CACHE_SYNC_OPTS, verbose=verbose,
                     retry_fetches=retry_fetches)

    self.m.repo.ensure_synced_checkout(sync_path, manifest.url,
                                       init_opts=init_opts, sync_opts=sync_opts,
                                       projects=projects)
    # Sync all branches of the internal manifest, so that we can find branches.
    with self.m.step.nest('sync manifest branches'):
      sync_opts.update(current_branch=False, projects=[manifest.project])
      with self.m.context(cwd=self.cache_path):
        self.m.repo.sync(**sync_opts)

  @contextlib.contextmanager
  def checkout_overlays_context(self):
    """Returns a context where overlays can be mounted."""
    with self.m.overlayfs.cleanup_context():
      if not self._enable_custom_overlays:
        self.m.overlayfs.mount('chromiumos', self.preload_path, self.cache_path,
                               persist=True)
        self.m.path.mock_add_paths(self.cache_path.join('.repo'))
        self.m.overlayfs.mount('workspace', self.cache_path,
                               self.workspace_path)
        self.m.path.mock_add_paths(self.workspace_path.join('.repo'))
      yield

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
      List[ProjectCommit]: A list of commits from cherry-picked patch sets.
    """
    # If make_manifest_changes_active is set, we need files_info for the
    # changes.
    include_files |= self._make_manifest_changes_active
    self._is_source_dirty = True

    patch_sets = self.m.gerrit.fetch_patch_sets(
        gerrit_changes, include_commit_info=include_commit_info,
        include_files=include_files, test_output_data=test_output_data)

    if self._make_manifest_changes_active:
      self._apply_manifest_patch_sets(patch_sets)

    return self._apply_gerrit_patch_sets(
        patch_sets, ignore_missing_projects=ignore_missing_projects)

  def _apply_manifest_patch_sets(self, patch_sets):
    """Apply any manifest patch sets, and make them active.

    If there are any manifest patch sets, then apply them to the manifest, and
    make that the active manifest.  If we are on a pinned manifest, then switch
    to the unpinned version before applying patches.

    Args:
      patch_sets (list[PatchSet]): patch sets to consider.
    """

    manifests, patches = self._partition_patches(patch_sets)
    if not patches.manifest:
      # There are no manifest changes. We are done.
      return

    with self.m.step.nest('patch manifest') as pres:
      branches = set(x.branch for x in patches.manifest)
      if len(branches) > 1:
        raise StepFailure('Cannot patch multiple branches: {}'.format(' '.join(
            sorted(branches))))
      branch = branches.pop()
      self.m.easy.set_properties_step(manifest_branch=branch)

      # Now we know what branch we need to be on, and we need the manifest
      # repo(s) to be on that branch so that the CLs will apply.
      self.checkout_branch(manifests.build.url, branch,
                           sync_opts=dict(current_branch=True, detach=True))

      _changes_full_xml = lambda p: any('full.xml' in x.file_infos for x in p)

      # If there are changes to the external copy of full.xml, that is an error.
      if _changes_full_xml(patches.build if manifests.build ==
                           manifests.extern else patches.extern):
        raise StepFailure('Full.xml changes must be made in manifest-internal')

      # If patches.intern changes full.xml, then:
      # 1. We do not have the internal manifest checked out, and
      # 2. We will need it so taht we can copy full.xml over to the external
      #    manifest.
      if _changes_full_xml(patches.intern):
        with self.m.step.nest('sync internal manifest for patching'):
          # Fetch the internal manifest into its path.  Use the (synced) cache
          # as a reference, so that we do not use the network for this.
          self.m.git.clone(
              manifests.intern.url, target_path=manifests.intern.path,
              reference=self.cache_path.join(manifests.intern.relpath),
              dissociate=True, timeout_sec=60 * 60)

      def _copy_full_xml():
        # Copy full.xml from internal to external manifest and commit
        i_full = manifests.intern.path.join('full.xml')
        e_full = manifests.extern.path.join('full.xml')
        self.m.file.copy('copy full.xml', i_full, e_full)
        with self.m.context(cwd=manifests.extern.path):
          self.m.git.add([e_full])
          res = self.m.git.commit(
              'Syncing with internal manifest.',
              stdout=self.m.raw_io.output(add_output_log=True),
              test_stdout='HEAD detached at 99caf97f', ok_ret=(0, 1))
          clean_msg = 'nothing to commit, working tree clean'
          if clean_msg in res.stdout.splitlines():
            return False
          elif res.retcode:
            raise StepFailure('git commit', result=res)
          return True

      changed = self._apply_partitioned_manifest_patches(manifests, patches)
      if _changes_full_xml(patches.intern + patches.build):
        changed |= _copy_full_xml()
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
      default_file = manifests.build.path.join('default.xml')

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
        self.m.step('clone', ['git', 'clone', '--bare', '.', new_dir])

        # Determine the correct name for the remote.
        step_test_data = lambda: self.m.raw_io.test_api.output(
            'cros-internal' if manifests.build == manifests.intern else 'cros')
        remote = self.m.step('remote', ['git', 'remote'],
                             stdout=self.m.raw_io.output(),
                             step_test_data=step_test_data).stdout.strip()

        # Now push the manifest repo, and make the branches look as they
        # should for this to be build_manifest.url.
        self.m.step('push', [
            'git', 'push', new_dir,
            '+refs/remotes/{}/*:refs/heads/*'.format(remote),
            '+refs/heads/{}:refs/heads/{}'.format(branch, branch)
        ])

      # 3. Switch to the newly cloned mirror.  Tip-of-tree for for the original
      #    branch is the patched version of the |gitiles_commit| manifest.
      # This will finally use the patched manifest to fetch the tree.  Since
      # source repos may have changed, etc, we need to use force_sync=True.
      #
      # This also means that the build manifest directory will be reset to the
      # unpatched version, which we will fix momentarily.
      init_opts = dict(manifest_branch=branch, manifest_name=default_file)
      sync_opts = dict(DEFAULT_CACHE_SYNC_OPTS, manifest_name=default_file,
                       current_branch=True, no_tags=False, retry_fetches=2,
                       detach=False, force_sync=True, no_manifest_update=True)
      self.m.repo.ensure_synced_checkout(self.workspace_path,
                                         'file://%s' % new_dir,
                                         init_opts=dict(init_opts),
                                         sync_opts=dict(sync_opts))

      # 4. Move the manifest directory (or both) back to the correct position.
      with self.m.step.nest('restore manifest patches'):
        with self.m.context(cwd=manifests.build.path):
          self.m.step('branch {}'.format(branch), ['git', 'checkout', branch])
          self.m.step('reset {}'.format(branch),
                      ['git', 'reset', '--hard', head])
        if manifests.build.path != manifests.extern.path:
          with self.m.context(cwd=manifests.extern.path):
            self.m.step('branch {}'.format(branch), ['git', 'checkout', branch])
            self.m.step('reset {}'.format(branch),
                        ['git', 'reset', '--hard', e_head])

      # 5. Log a pinned version of the patched manifest.
      final = self.m.repo.manifest(pinned=True)
      self._pinned_manifest = final
      pres.logs['patched-manifest.xml'] = [final]

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
      if not patch_sets:
        return []
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
        manifest, but the CQ run includes private changes.)
      project_path (str): The path to use when applying the patch, or none to
        use find_project_paths.
      name (str): The name for the step, or None.

    Returns:
      List[ProjectCommit]: A list of commits from cherry-picked patch sets.
    """
    with self.m.step.nest(name or 'apply gerrit patch sets') as pres:
      if ignore_missing_projects:
        synced_projects = set(p.name for p in self.m.repo.project_infos())
        # Only retain patches to synced projects.  Mark as discarded any patches
        # to other projects, unless they have already been applied (manifest
        # patches).
        discard = [
            p for p in patch_sets if p.project not in synced_projects and
            p.display_id not in self._applied_patches
        ]
        patch_sets = [p for p in patch_sets if p.project in synced_projects]
        if discard:
          pres.step_text = 'Discarded changes: {}'.format(', '.join(
              p.display_id for p in discard))

      new_commits = []
      for patch in patch_sets:
        if patch.display_id not in self._applied_patches:
          project_paths = ([project_path] if project_path else
                           self.find_project_paths(patch.project, patch.branch))
          for path in project_paths:
            self._apply_patch_set(patch, path)
        new_commits.extend(self._applied_patches[patch.display_id])
      return new_commits

  def _apply_patch_set(self, patch, project_path):
    """Apply a PatchSet to the git repo in ${CWD}.

    Args:
      patch (PatchSet): The PatchSet to apply.
      project_path (str): The path (relative to the workspace) in which to apply
        the change.

    Returns:
      (ProjectCommit) commit for the applied patch.
    """
    with self.m.context(cwd=self.workspace_path.join(project_path)):
      commit = self.m.git.fetch_ref(patch.git_fetch_url, patch.git_fetch_ref)
      merged = self.m.git.merge_silent_fail(commit, 'merge gerrit changes',
                                            infra_step=False)
      if not merged:
        self.m.git.merge_abort()
        if self.m.git.is_merge_commit(commit):
          raise StepFailure(
              'merge %s failed. Aborting: cannot cherry-pick merge commits' %
              commit)
        presentation = self.m.step.active_result.presentation
        presentation.status = self.m.step.SUCCESS
        presentation.step_text = 'merge failed. will try cherry-pick instead'
        self.m.git.cherry_pick(commit, infra_step=False)

      new_commit = ProjectCommit(project_path, self.m.git.head_commit(), patch)
      self._applied_patches[patch.display_id].append(new_commit)
      return new_commit

  retry_timeouts = lambda e: getattr(e, 'had_timeout', False)

  @exponential_retry(retries=3, condition=retry_timeouts)
  def sync_snapshot(self, gitiles_commit, manifest_url=None):
    """Sync a checkout to the snapshot.

    Args:
      gitiles_commit (GitilesCommit): commit to sync to
      manifest_url: URL of manifest repo.  Default: internal manifest
    """
    manifest_url = manifest_url or self.m.src_state.internal_manifest.url
    with self.m.step.nest('sync to snapshot'):
      snapshot_xml = self._get_snapshot(gitiles_commit)
      self.m.repo.sync_manifest(manifest_url, manifest_data=snapshot_xml,
                                detach=True, optimized_fetch=True,
                                retry_fetches=8)
      # Get the pinned manifest from repo.  If that returns None, then we
      # already have the pinned manifest in snapshot_xml.
      self._pinned_manifest = (
          self.m.repo.ensure_pinned_manifest(test_data='') or snapshot_xml)

  def _get_snapshot(self, gitiles_commit):
    """Returns the snapshot to use.

    Returns the snapshot to use. If a custom snapshot has been provided
    via an input property, that will be used. Otherwise it will fall back
    to the typical syncing to the gitiles_commit.
    """
    if self._snapshot_isolate:
      return self._get_snapshot_from_isolate()
    return self._get_snapshot_from_gitiles(gitiles_commit)

  def _get_snapshot_from_isolate(self):
    """Returns the snapshot to use from isolate"""
    si = self._snapshot_isolate
    snapshot_dir = self.m.path.mkdtemp('snapshot')
    self.m.isolated.download('download snapshot.xml from isolate',
                             isolated_hash=si.isolated_hash,
                             isolate_server=si.isolate_server,
                             output_dir=snapshot_dir)
    return self.m.file.read_text('read snapshot.xml',
                                 snapshot_dir.join('snapshot.xml'),
                                 test_data='<manifest></manifest>')

  def _get_snapshot_from_gitiles(self, gitiles_commit):
    """Returns the snapshot to use from gitiles."""
    gitiles_url = 'https://%s/%s' % (gitiles_commit.host,
                                     gitiles_commit.project)

    testdata = '<manifest></manifest>'
    step_test_data = lambda: self.m.gitiles.test_api.make_encoded_file(testdata)

    data = self.m.gitiles.download_file(
        gitiles_url, 'snapshot.xml', branch=gitiles_commit.id,
        step_test_data=step_test_data, accept_statuses=[200, 404],
        timeout=self.test_api.gitiles_timeout_seconds)
    if data:
      return data

    # If there is no snapshot.xml, then we need to go to the appropriate
    # branch of the appropriate manifest and generate the manifest.
    manifest = self.m.src_state.gitiles_commit_to_manifest(gitiles_commit)
    with self.m.context(cwd=manifest.path):
      self.checkout_branch(manifest.url, gitiles_commit.ref)
      self.m.git.fetch(manifest.remote, [gitiles_commit.id])
      self.m.git.checkout(gitiles_commit.id, force=True)
      snapshot_path = manifest.path.join('snapshot.xml')
      # If the branch is pinned, use snapshot.xml, otherwise generate an
      # unpinned manifest and return that.
      return (self.m.file.read_raw('read local snapshot.xml', snapshot_path,
                                   test_data=testdata)
              if self.m.path.exists(snapshot_path) else self.m.repo.manifest(
                  manifest_file=manifest.path.join('default.xml'),
                  pinned=False))

  def create_project_commits_archive(self, archive_path, project_commits):
    """Creates an archive with the given project commits from the workspace.

    This uses `git bundle` to efficiently store diffs. The recipient of this
    archive must have appropriate parent commits locally available to use
    this archive with 'checkout_project_commits_archive'.

    Args:
      archive_path (Path): Path to archive file to create. Uses the 'archive'
        module and inherits its archive type file extension detection.
      project_commits (List[ProjectCommit]): Commits to add to archive. Must be
        in patch application order.
    """
    with self.m.step.nest('create project commits archive'):
      # Find first commit for each project and make a reference to its parent.
      project_base_commits = {}
      for project_commit in project_commits:
        project_base_commits.setdefault(project_commit.path,
                                        '%s^' % project_commit.commit_id)

      # NOTE: The contents of this archive are an implementation detail of
      # this module. For each project with commit(s) in the archive, a `git
      # bundle` file is included in the archive at
      # 'projects/<project path>/bundle'.
      archive_root = self.m.path.mkdtemp('create_project_commits_archive')
      package = self.m.archive.package(archive_root)
      for project_relpath, base_commit_id in project_base_commits.items():
        archive_project_path = archive_root.join('projects', project_relpath)
        self.m.file.ensure_directory('project path', archive_project_path)
        with self.m.context(cwd=self.workspace_path.join(project_relpath)):
          bundle_path = archive_project_path.join('bundle')
          self.m.git.create_bundle(bundle_path, base_commit_id, 'HEAD')
          package.with_file(bundle_path)

      # A metadata.json file includes information about the included bundles.
      metadata_path = archive_root.join('metadata.json')
      metadata = {'project_paths': project_base_commits.keys()}
      self.m.file.write_text('metadata.json', metadata_path,
                             json.dumps(metadata))
      package.with_file(metadata_path)

      package.archive('create archive', archive_path)

  def checkout_project_commits_archive(self, archive_path):
    """Checkout the commits in the given archive file into the workspace.

    See 'create_project_commits_archive'. The local source tree must have all
    appropriate parent commits locally available to apply an archive.

    Args:
      archive_path (Path): Path to the archive.

    Returns:
      List[str]: List of project paths with commits in the archive.
    """
    with self.m.step.nest('checkout project commits archive'):
      # The archive root must not exist prior to 'extract'.
      archive_workdir = self.m.path.mkdtemp('checkout_project_commits_archive')
      archive_root = archive_workdir.join('archive')
      self.m.archive.extract('extract archive', archive_path, archive_root)

      metadata_path = archive_root.join('metadata.json')
      metadata = json.loads(
          self.m.file.read_text(
              'metadata.json', metadata_path,
              test_data='{"project_paths": ["a/b", "a/b/c"]}'))

      # Checkout bundles into their projects.
      for project_relpath in metadata['project_paths']:
        with self.m.context(cwd=self.workspace_path.join(project_relpath)):
          bundle_path = archive_root.join(project_relpath, 'bundle')
          self.m.git.fetch_ref(bundle_path, 'HEAD')
          self.m.git.checkout('FETCH_HEAD')

      return metadata['project_paths']
