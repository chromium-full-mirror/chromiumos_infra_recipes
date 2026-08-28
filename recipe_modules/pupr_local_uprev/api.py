# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to create uprevs on the local checkout for PUpr (Parallel Uprevs)."""

import collections
import dataclasses
import json
from typing import Any, DefaultDict, NamedTuple
from urllib.parse import urlparse

from recipe_engine import config_types
from recipe_engine import recipe_api

from PB.chromite.api import packages as packages_pb2
from PB.chromite.api import sdk as sdk_pb2
from PB.chromiumos import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.recipes.chromeos import generator as generator_pb2
from RECIPE_MODULES.chromeos.pupr.api import UPREV_VERSION_LABEL
from RECIPE_MODULES.chromeos.repo import api as repo_api


@dataclasses.dataclass(frozen=True)
class LocalUprevConfig:
  """Configuration for a local PUpr uprev run."""
  additional_commit_message: str
  additional_commit_footer: str
  allow_partial_uprev: bool
  packages: tuple[common_pb2.PackageInfo, ...]
  build_targets: tuple[common_pb2.BuildTarget, ...]
  uprev_target_kind: generator_pb2.UprevTargetKind | None
  version_files: tuple[str, ...]

  @classmethod
  def for_test(
      cls,
      additional_commit_message: str = '',
      additional_commit_footer: str = '',
      allow_partial_uprev: bool = False,
      packages: tuple[common_pb2.PackageInfo, ...]
      | list[common_pb2.PackageInfo] | None = None,
      build_targets: tuple[common_pb2.BuildTarget, ...]
      | list[common_pb2.BuildTarget] | None = None,
      uprev_target_kind: generator_pb2.UprevTargetKind | None = None,
      version_files: tuple[str, ...] | list[str] | None = None,
  ) -> 'LocalUprevConfig':
    """Factory to construct config with sensible defaults for test cases."""
    return cls(
        additional_commit_message=additional_commit_message,
        additional_commit_footer=additional_commit_footer,
        allow_partial_uprev=allow_partial_uprev,
        packages=tuple(packages) if packages is not None else (),
        build_targets=tuple(build_targets) if build_targets is not None else (),
        uprev_target_kind=uprev_target_kind,
        version_files=tuple(version_files) if version_files is not None else (),
    )


class Ebuild(NamedTuple):
  path: str
  version: str
  commit_info: str


class PuprLocalUprevApi(recipe_api.RecipeApi):
  """A module to create local uprevs for PUpr."""

  def __init__(self, properties, *args: Any, **kwargs: Any):
    """Initialize the module's attributes."""
    super().__init__(*args, **kwargs)
    self.properties = properties
    self.config = LocalUprevConfig.for_test()

  @property
  def workspace_path(self) -> config_types.Path:
    """Return the checkout path where the build is processed."""
    return self.m.cros_source.workspace_path

  def set_generator_config(self, config: LocalUprevConfig) -> None:
    """Set the full uprev configuration dataclass."""
    self.config = config

  def uprev_packages(
      self,
      versions: list[packages_pb2.UprevVersionedPackageRequest.GitRef],
      topic: str,
      change_id: str = '',
  ) -> list[repo_api.ProjectInfo] | None:
    """Try to uprev the specified packages. If successful, commit the uprev.

    Args:
      versions: The versions to consider for an update.
      change_id: If given, set Change-Id to the commit message, so that the
        commit is uploaded as a new patch set of an existing Change. When this
        is set, the uprev should not span multiple repositories.
      topic: A short string with which to tag all generated commits.

    Returns:
      If packages are successfully uprevved, return a list of ProjectInfos
        for all repo projects with modified code.
      If not all packages are uprevved and allow_partial_uprev==False, return
        None. This signifies that the PUpr run should terminate immediately.
    """
    modified_package_names: list[str] = []
    all_valid_responses: list[packages_pb2.UprevPackagesResponse] = []
    for package in self.config.packages:
      package_responses = self._uprev_package(package, versions)
      if package_responses:
        all_valid_responses.extend(package_responses)
        modified_package_names.append(package.package_name)
      elif not self.config.allow_partial_uprev:
        return None
    if not all_valid_responses:
      return None
    return self._commit_package_uprevs(versions, all_valid_responses,
                                       modified_package_names, topic,
                                       change_id=change_id)

  def _uprev_package(
      self,
      package: common_pb2.PackageInfo,
      versions: list[packages_pb2.UprevVersionedPackageRequest.GitRef],
  ) -> list[packages_pb2.UprevPackagesResponse]:
    """Locally uprev a single package.

    Args:
      package: The package to uprev.
      versions: The versions to consider for an update.

    Returns:
      List of UprevPackageResponses that actually changed code.
    """
    cpv = self.m.naming.get_package_title(package)
    with self.m.step.nest('try uprev {}'.format(cpv)) as presentation:
      request = packages_pb2.UprevVersionedPackageRequest(
          chroot=self.m.cros_sdk.chroot,
          package_info=package,
          versions=versions,
          build_targets=self.config.build_targets,
      )
      presentation.logs['request'] = str(request)
      response = self.m.cros_build_api.PackageService.UprevVersionedPackage(
          request, name='uprev versioned package')

      if not response.responses:
        presentation.step_text = 'no new versions for {}'.format(cpv)
        return []

      valid_responses: list[packages_pb2.UprevPackagesResponse] = []
      with self.m.step.nest('verify updates'):
        for uprev_resp in response.responses:
          if self._uprev_packages_response_has_changes(uprev_resp):
            valid_responses.append(uprev_resp)

      if not valid_responses:
        presentation.step_text = (
            'skipping uprev for {}. no modified files'.format(cpv))
        if not self.config.allow_partial_uprev:
          return []
        presentation.logs[
            'partial_uprev'] = 'no modified file for {}. continue because allow_partial_uprev=True'.format(
                cpv)
        return []

      presentation.logs['uprev versions'] = [
          response.version for response in valid_responses
      ]
    return valid_responses

  def _commit_package_uprevs(
      self, versions: list[packages_pb2.UprevVersionedPackageRequest.GitRef],
      uprev_packages_responses: list[packages_pb2.UprevPackagesResponse],
      modified_package_names: list[str], topic: str,
      change_id: str = '') -> list[repo_api.ProjectInfo]:
    """Commit the package uprevs on the local filesystem.

    Args:
      versions: The versions to consider for an update.
      uprev_packages_responses: BAPI responses for all uprevs that actually
          produced code changes.
      modified_package_names: The names of packages that are modified.
      change_id: If given, set Change-Id to the commit message, so that the
        commit is uploaded as a new patch set of an existing Change. When this
        is set, the uprev should not span multiple repositories.
      topic: A short string with which to tag all generated commits.

    Returns:
      A list of ProjectInfos for repo projects with modified code.
    """
    with self.m.step.nest('commit uprev'):
      # Flatten the list of modified files.
      modified_ebuilds: list[Ebuild] = []
      for uprev_resp in uprev_packages_responses:
        modified_ebuilds.extend(
            Ebuild(path=ebuild.path, version=uprev_resp.version,
                   commit_info=uprev_resp.additional_commit_info)
            for ebuild in uprev_resp.modified_ebuilds)

      # Sort ebuilds by repo project.
      with self.m.context(cwd=self.workspace_path):
        ebuilds_by_project: DefaultDict[repo_api.ProjectInfo, list[Ebuild]]
        ebuilds_by_project = collections.defaultdict(list)
        for ebuild in modified_ebuilds:
          dirname = self.m.path.dirname(ebuild.path)
          project_info = self.m.repo.project_infos(projects=[dirname])[0]
          ebuilds_by_project[project_info].append(ebuild)

      self._create_pupr_branches(list(ebuilds_by_project))

      # For each repository, make the commit.
      for project, ebuilds in sorted(ebuilds_by_project.items()):
        name = self.m.path.basename(project.path)
        root = self.workspace_path / project.path
        uprevved_versions = sorted(set(e.version for e in ebuilds))
        additional_msg = '\n'.join(
            sorted(set(e.commit_info for e in ebuilds if e.commit_info)))
        commit_message = self._create_commit_message(
            ', '.join(modified_package_names),
            uprevved_versions,
            topic,
            target_refs=versions,
            additional_msg=additional_msg,
            change_id=change_id,
        )
        with self.m.step.nest(f'commit in {name}'), self.m.context(cwd=root):
          self.m.git.add([ebuild.path for ebuild in ebuilds])
          self.m.git.commit(commit_message)

    return list(ebuilds_by_project)

  def _create_pupr_branches(self, projects: list[repo_api.ProjectInfo]) -> None:
    """Create Git branches for all the given repo projects.

    Create branches via `repo` so that they track correctly.
    Create them by path instead of by project name, because they may be checked
    out multiple times.
    """
    with self.m.context(cwd=self.workspace_path):
      project_paths = sorted([project.path for project in projects])
      self.m.repo.start('pupr', projects=project_paths)

  def _create_commit_message(
      self, prefix: str, uprevved_versions: list[str], topic: str,
      target_refs: list[packages_pb2.UprevVersionedPackageRequest.GitRef]
      | None = None, additional_msg: str = '', change_id: str = '') -> str:
    """Create a commit message for the uprev.

    Sample commit message:

      my_prefix: Automatic uprev to version1, version2.

      Additional message, as provided by input properties.
      Additional message, as provided by kwargs.
      It can even span multiple lines!

      Generated by PUpr, see go/bbid/12345 for job details.

      BUG=None
      TEST=CQ

      Pupr-Upstream-Versions: [{"ref": "refs/heads/main", "repository":
      "/chromiumos/overlays/chromiumos-overlay", "revision": "deadbeef007"}]
      Cq-Cl-Tag: pupr:my_topic

      Cq-Depend: chromium:12345,chrome-internal:67890
      Change-Id: I123456789abcdef

    Args:
      prefix: The beginning of the commit's subject line. For example, if the
        first line of the commit is "foo: Change some code", then the prefix
        is "foo".
      uprevved_versions: The versions to which the targets were actually
        uprevved.
      target_refs: GitRefs that were targeted for uprev. This should always be
        set for ebuild uprevs.
      additional_msg: If given, extra information to add to the commit message.
        This will be added after self.config.additional_commit_message.
      change_id: If given, set Change-Id to the commit message, so that the
        commit is uploaded as a new patch set of an existing Change. When this
        is set, the uprev should not span multiple repositories.
    """
    commit_lines = [
        f'{prefix}: Automatic uprev to {", ".join(uprevved_versions)}.', ''
    ]

    if self.config.additional_commit_message:
      commit_lines.append(
          self.config.additional_commit_message.format(
              versions=uprevved_versions, refs=target_refs))
    if additional_msg:
      commit_lines.append(additional_msg)

    build_url = self.m.buildbucket.build_url()
    commit_lines.extend([
        f'Generated by PUpr, see {build_url} for job details.',
        '',
        'BUG=None',
        'TEST=CQ',
    ])

    footers = []
    if target_refs:
      footers.append(
          f'{UPREV_VERSION_LABEL}: {_serialize_versions(target_refs)}')
    footers.append(f'Cq-Cl-Tag: pupr:{topic}')
    if self.m.src_state.gerrit_changes:
      depends: list[str] = []
      for change in self.m.src_state.gerrit_changes:
        host = change.host.split('.', 1)[0].replace('-review', '')
        depends.append(f'{host}:{change.change}')
      footers.append(f'Cq-Depend: {",".join(depends)}')
    if self.config.additional_commit_footer:
      footers.append(self.config.additional_commit_footer)
    if change_id:
      footers.append('Change-Id: ' + change_id)
    if footers:
      commit_lines.extend([''] + footers)

    return '\n'.join(commit_lines) + '\n'

  def uprev_sdk(self, topic: str) -> list[repo_api.ProjectInfo]:
    """Uprev the SDK on the local filesystem, and commit the uprev.

    Args:
      topic: A short string with which to tag all generated commits.

    Returns:
      A list of repo projects with modified code.
    """
    with self.m.step.nest('uprev sdk'):
      self._validate_sdk_uprev_spec()
      request = sdk_pb2.UprevRequest(
          binhost_gs_bucket=(self.properties.sdk_uprev_spec.binhost_gs_bucket or
                             'gs://chromeos-prebuilt/'),
          version=self.properties.sdk_uprev_spec.sdk_version,
          toolchain_tarball_template=(
              self.properties.sdk_uprev_spec.toolchain_template),
          sdk_gs_bucket=self.properties.sdk_uprev_spec.sdk_gs_bucket,
      )
      response = self.m.cros_build_api.SdkService.Uprev(request)
      return self._commit_sdk_uprev(response, topic)

  def _validate_sdk_uprev_spec(self) -> None:
    """For SDK uprevs, make sure that the necessary input properties are given.

    Raises:
      InfraFailure: If the SDK version is not specified.
      InfraFailure: If the toolchain template is not specified.
    """
    with self.m.step.nest('validate SDK uprev spec'):
      if not self.properties.sdk_uprev_spec.sdk_version:
        raise recipe_api.InfraFailure('No SDK version specified.')
      if not self.properties.sdk_uprev_spec.toolchain_template:
        raise recipe_api.InfraFailure('No toolchain template specified.')

  def _commit_sdk_uprev(self, uprev_sdk_response: sdk_pb2.UprevResponse,
                        topic: str) -> list[repo_api.ProjectInfo]:
    """Commit the SDK uprev on the local filesystem.

    uprev_sdk_response: The Build API response from uprevving the SDK.
    topic: A short string with which to tag all generated commits.

    Returns:
      A list of ProjectInfos for repo projects with modified code.
    """
    with self.m.step.nest('commit uprev'), self.m.context(
        cwd=self.workspace_path):
      modified_projects = sorted(
          set(
              self.m.repo.project_infos(
                  projects=[
                      path.path for path in uprev_sdk_response.modified_files
                  ], test_data=self.test_api.sdk_project_infos_step_data)))
      self._create_pupr_branches(modified_projects)
      commit_message = self._create_commit_message('SDK',
                                                   [uprev_sdk_response.version],
                                                   topic)

      # For each repository, make the commit.
      for project in modified_projects:
        name = self.m.path.basename(project.path)
        root = self.workspace_path / project.path
        with self.m.step.nest(f'commit in {name}'), self.m.context(cwd=root):
          self.m.git.add(['.'])
          self.m.git.commit(commit_message)

    return modified_projects

  def rebase_cl(self, open_changes: list[bb_common_pb2.GerritChange],
                topic: str, change_num: int) -> None:
    """Create a new uprev patch (locally) for change_id.

    Args:
      open_changes: List of currently open uprev CLs.
      change_num: Change number of the CL to rebase, as in crrev.com/c/#####.
      topic: A short string with which to tag all generated commits.

    Raises:
      StepFailure: If the uprev does not generate any changes, or if the uprev
        only uprevs some packages and allow_partial_uprev is False, or if the
        uprev requires a multi-repo commit.
    """
    with self.m.step.nest('rebase CL {}'.format(change_num)):
      retry_changes = [p for p in open_changes if p.change == change_num]
      assert len(retry_changes) == 1
      retry_change = retry_changes[0]
      # TODO(b/543713972): Make pupr_local_uprev purely local; avoid querying
      # Gerrit for change descriptions here and have the caller pass the
      # required metadata (e.g. Change-Id and existing versions) instead.
      description = self.m.gerrit.get_change_description(retry_change)
      change_ids = self.m.git_footers.from_message(description,
                                                   key='Change-Id') or []
      if len(change_ids) != 1:
        raise recipe_api.StepFailure(
            f'failed to find a single Change-Id in the Change description (found {len(change_ids)}): {description}'
        )
      change_id = change_ids[0]
      existing_versions = self.m.pupr.extract_upstream_git_refs(description)
      if existing_versions is None:
        raise recipe_api.StepFailure(
            f'failed to find {UPREV_VERSION_LABEL} in the Change description: {description}'
        )
      if self.config.uprev_target_kind == generator_pb2.UprevTargetKind.VERSION_FILE:
        version_file_refs = [
            packages_pb2.UprevVersionFileRequest.GitRef(repository=v.repository,
                                                        ref=v.ref,
                                                        revision=v.revision)
            for v in existing_versions
        ]
        modified_projects = self.uprev_version_files(version_file_refs, topic,
                                                     change_id=change_id)
      else:
        modified_projects = self.uprev_packages(existing_versions, topic,
                                                change_id=change_id)
      if not modified_projects:
        raise recipe_api.StepFailure('The uprev had no file.')
      if len(modified_projects) > 1:
        raise recipe_api.StepFailure(
            'The uprev requires multi-repo commit. Cannot be rebased. {}'
            .format(sorted(modified_projects)))

  def uprev_version_files(
      self,
      versions: list[packages_pb2.UprevVersionFileRequest.GitRef],
      topic: str,
      change_id: str = '',
  ) -> list[repo_api.ProjectInfo] | None:
    """Try to uprev the specified version files. If successful, commit the uprev.

    Args:
      versions: The versions to consider for an update.
      change_id: If given, set Change-Id to the commit message.
      topic: A short string with which to tag all generated commits.

    Returns:
      If version files are successfully uprevved, return a list of ProjectInfos
        for all repo projects with modified code.
      If not all version files are uprevved and allow_partial_uprev==False, return
        None. This signifies that the PUpr run should terminate immediately.
    """
    modified_file_paths: list[str] = []
    all_valid_responses: list[packages_pb2.UprevFileResponse] = []
    for file_path in self.config.version_files:
      file_responses = self._uprev_version_file(file_path, versions)
      if file_responses:
        all_valid_responses.extend(file_responses)
        modified_file_paths.append(file_path)
      elif not self.config.allow_partial_uprev:
        return None
    if not all_valid_responses:
      return None

    return self._commit_file_uprevs(versions, all_valid_responses, topic,
                                    change_id=change_id)

  def _uprev_version_file(
      self,
      file_path: str,
      versions: list[packages_pb2.UprevVersionFileRequest.GitRef],
  ) -> list[packages_pb2.UprevFileResponse]:
    """Locally uprev a single version file.

    Args:
      file_path: The file path to uprev.
      versions: The versions to consider for an update.

    Returns:
      List of UprevFileResponses that actually changed code.
    """
    with self.m.step.nest('try uprev {}'.format(file_path)) as presentation:
      request = packages_pb2.UprevVersionFileRequest(
          chroot=self.m.cros_sdk.chroot,
          file_path=file_path,
          versions=versions,
      )
      presentation.logs['request'] = str(request)
      response = self.m.cros_build_api.PackageService.UprevVersionFile(
          request, name='uprev version file')

      if not response.responses:
        presentation.step_text = 'no new versions for {}'.format(file_path)
        return []

      valid_responses: list[packages_pb2.UprevFileResponse] = []
      with self.m.step.nest('verify updates'):
        for uprev_resp in response.responses:
          if self._uprev_file_response_has_changes(uprev_resp):
            valid_responses.append(uprev_resp)

      if not valid_responses:
        presentation.step_text = (
            'skipping uprev for {}. no modified files'.format(file_path))
        return []

      presentation.logs['uprev versions'] = [
          resp.version for resp in valid_responses
      ]
    return valid_responses

  def _commit_file_uprevs(
      self, versions: list[packages_pb2.UprevVersionFileRequest.GitRef],
      uprev_file_responses: list[packages_pb2.UprevFileResponse], topic: str,
      change_id: str = '') -> list[repo_api.ProjectInfo]:
    """Commit the file uprevs on the local filesystem.

    Args:
      versions: The versions to consider for an update.
      uprev_file_responses: BAPI responses for all uprevs that actually
          produced code changes.
      change_id: If given, set Change-Id to the commit message.
      topic: A short string with which to tag all generated commits.

    Returns:
      A list of ProjectInfos for repo projects with modified code.
    """
    with self.m.step.nest('commit uprev'):
      # Flatten the list of modified files.
      modified_files: list[str] = []
      for uprev_resp in uprev_file_responses:
        modified_files.extend(uprev_resp.modified_files)

      chrome_files: list[str] = []
      repo_files_by_project: DefaultDict[repo_api.ProjectInfo, list[str]]
      repo_files_by_project = collections.defaultdict(list)

      chrome_root = self.m.path.start_dir / 'chrome'
      chrome_root_str = str(self.m.path.abs_to_path(chrome_root))
      for path in modified_files:
        if str(self.m.path.abs_to_path(path)).startswith(chrome_root_str):
          chrome_files.append(path)
        else:
          with self.m.context(cwd=self.workspace_path):
            dirname = self.m.path.dirname(path)
            project_info = self.m.repo.project_infos(projects=[dirname])[0]
            repo_files_by_project[project_info].append(path)

      # Create branches
      if repo_files_by_project:
        self._create_pupr_branches(list(repo_files_by_project))
      if chrome_files:
        chrome_src_root = chrome_root / 'src'
        with self.m.context(cwd=chrome_src_root):
          base_branch = self.m.git.current_branch() or 'main'
          if self.m.git.branch_exists('pupr'):
            head = self.m.git.head_commit()
            self.m.git.checkout(commit=head)
            self.m.git.delete_local_branch('pupr')
          self.m.git.checkout(branch='pupr')

      # TODO(b/493779542): Unify the two commit paths below (repo_files_by_project and chrome_files).
      # For each repository, make the commit.
      modified_projects = []
      for project, paths in sorted(repo_files_by_project.items()):
        name = self.m.path.basename(project.path)
        root = self.workspace_path / project.path
        rel_paths = [
            str(self.m.path.relpath(self.m.path.abs_to_path(p), root))
            for p in paths
        ]
        prefix = ', '.join(rel_paths)
        uprevved_versions = sorted(set(r.version for r in uprev_file_responses))
        target_refs = [
            packages_pb2.UprevVersionedPackageRequest.GitRef(
                repository=v.repository, ref=v.ref, revision=v.revision)
            for v in versions
        ]
        additional_msg = '\n'.join(
            sorted(
                set(r.additional_commit_info
                    for r in uprev_file_responses
                    if r.additional_commit_info)))
        commit_message = self._create_commit_message(
            prefix,
            uprevved_versions,
            topic,
            target_refs=target_refs,
            additional_msg=additional_msg,
            change_id=change_id,
        )
        with self.m.step.nest(f'commit in {name}'), self.m.context(cwd=root):
          self.m.git.add(paths)
          self.m.git.commit(commit_message)
        modified_projects.append(project)

      if chrome_files:
        chrome_src_root = chrome_root / 'src'
        uprevved_versions = sorted(set(r.version for r in uprev_file_responses))
        target_refs = [
            packages_pb2.UprevVersionedPackageRequest.GitRef(
                repository=v.repository, ref=v.ref, revision=v.revision)
            for v in versions
        ]
        rel_paths = [
            str(
                self.m.path.relpath(
                    self.m.path.abs_to_path(p), chrome_src_root))
            for p in chrome_files
        ]
        prefix = ', '.join(rel_paths)
        additional_msg = '\n'.join(
            sorted(
                set(r.additional_commit_info
                    for r in uprev_file_responses
                    if r.additional_commit_info)))
        commit_message = self._create_commit_message(
            prefix,
            uprevved_versions,
            topic,
            target_refs=target_refs,
            additional_msg=additional_msg,
            change_id=change_id,
        )
        with self.m.step.nest('commit in chrome'), self.m.context(
            cwd=chrome_src_root):
          rel_paths = [
              self.m.path.relpath(p, chrome_src_root) for p in chrome_files
          ]
          self.m.git.add(rel_paths)
          self.m.git.commit(commit_message)
          # Resolve project info for chrome repository
          remote_url = self.m.git.remote_url(remote='origin')
          remote_host = urlparse(remote_url).netloc
          remote = 'cros-internal' if 'chrome-internal' in remote_host else 'cros'
          branch = base_branch
          project_name = urlparse(remote_url).path.strip('/')
          if project_name.startswith('a/'):
            project_name = project_name[2:]
          if project_name.endswith('.git'):
            project_name = project_name[:-4]
          chrome_project = repo_api.ProjectInfo(
              remote=remote,
              name=project_name,
              branch=branch,
              rrev='refs/heads/' + branch,
              path=str(chrome_src_root),
          )
        modified_projects.append(chrome_project)

    return modified_projects

  def _uprev_packages_response_has_changes(
      self, response: packages_pb2.UprevPackagesResponse) -> bool:
    """Return whether the given `UprevPackagesResponse` has changes."""
    return self._has_git_changes(
        [ebuild.path for ebuild in response.modified_ebuilds])

  def _uprev_file_response_has_changes(
      self, response: packages_pb2.UprevFileResponse) -> bool:
    """Return whether the given `UprevFileResponse` has changes."""
    return self._has_git_changes(response.modified_files)

  def _has_git_changes(self, paths: list[str]) -> bool:
    """Return whether any of the given paths has git diff changes."""
    for path in paths:
      with self.m.context(
          cwd=self.m.path.abs_to_path(self.m.path.dirname(path))):
        if self.m.git.diff_check(path):
          return True
    return False


# TODO(b/543713972): Use a trigger proto (e.g., GitilesTrigger) instead of
# packages_pb2.UprevVersionedPackageRequest.GitRef for serializing upstream
# version metadata.
def _serialize_versions(
    versions: list[packages_pb2.UprevVersionedPackageRequest.GitRef]) -> str:
  """Serialize versions information.

  Args:
    versions: The versions to consider for an update.

  Returns:
    A JSON string that encodes the input.
  """
  o = [{
      'ref': v.ref,
      'repository': v.repository,
      'revision': v.revision,
  } for v in versions]
  return json.dumps(o)
