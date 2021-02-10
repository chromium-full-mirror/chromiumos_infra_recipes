# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds chromeos-firmware on a firmware branch."""

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'build_menu',
    'cros_sdk',
    'cros_version',
    'src_state',
    'test_util',
]

from contextlib import contextmanager
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.recipes.chromeos.build_legacy_fw import BuildLegacyFwProperties
from PB.chromiumos import common
from PB.chromite.api import firmware

PROPERTIES = BuildLegacyFwProperties
_FIRMWARE_TARBALL_NAME = 'firmware_from_source.tar.bz2'
_FIRMWARE_METADATA_NAME = 'firmware_metadata.jsonpb'


# The age of the branches is such that we do not even have a Build API for the
# most part.
class FirmwareBuilder(object):

  def __init__(self, api, properties):
    self.m = api
    self.properties = properties
    assert properties.build_target.name, 'build_target must be set'
    self.board = '--board={}'.format(properties.build_target.name)
    self._legacy_setup_board = api.path.exists(
        api.src_state.workspace_path.join('src', 'scripts', 'setup_board'))
    self._chroot = self.m.src_state.workspace_path.join('chroot')
    self._sysroot = self._chroot.join('build', properties.build_target.name)
    self._config = None

  def __call__(self, name, cmd, **kwargs):
    """Run cros_sdk with the given command"""
    kwargs.setdefault('infra_step', True)
    kwargs.setdefault('wrapper', [self.m.cros_sdk.cros_sdk_path])
    return self.m.step(name, cmd, **kwargs)

  @contextmanager
  def _setup(self):
    """Configure the builder"""
    # If we do not have a gitiles_commit from buildbucket, and input properties
    # has manifest_branch, use that branch of the internal manifest.
    commit = self.m.src_state.gitiles_commit
    if not commit.project and self.properties.manifest_branch:
      commit = self.m.src_state.internal_manifest.as_gitiles_commit_proto
      commit.ref = 'refs/heads/{}'.format(self.properties.manifest_branch)

    with self.m.build_menu.configure_builder(commit=commit,
                                             disable_sdk=True) as config:
      self._config = config
      with self.m.build_menu.setup_workspace(), \
          self.m.context(cwd=self.m.src_state.workspace_path), \
          self.m.depot_tools.on_path(), self._setup_chroot():
        yield

  @contextmanager
  def _setup_chroot(self):
    try:
      self('init SDK', ['--delete', '--create'])
      self('update SDK', ['./update_chroot'])
      yield
    finally:
      self('delete SDK', ['--delete'])

  def _setup_board(self):
    if self._legacy_setup_board:
      cmd = [
          './setup_board', self.board, '--accept_licenses=@CHROMEOS',
          '--skip_chroot_upgrade'
      ]
    else:
      cmd = [
          'setup_board', self.board, '--accept-licenses=@CHROMEOS',
          '--skip-chroot-upgrade'
      ]
    self('setup board', cmd)

  def _install_packages(self):
    # TODO(b/179154813): We probably need to include USE flags from properties
    # or builder_config.
    cmd = [
        './build_packages', self.board, '--accept_licenses=@CHROMEOS',
        '--skip_chroot_upgrade'
    ] + [
        '{}/{}'.format(x.category, x.package_name)
        for x in self.properties.packages
    ]
    self('install packages', cmd, infra_step=False)

  def _build_firmware_archive(self, out_path):
    with self.m.step.nest('create firmware archive') as pres:
      # This code replicates chromite/service/artifacts.BuildFirmwareArchive.
      self.m.file.ensure_directory('create tempdir', out_path)
      root = self._sysroot.join('firmware')

      private_dirs = self.m.file.glob_paths(
          'glob private', root, '**/ec-private/fingerprint',
          test_data=['foo/ec-private/fingerprint'])

      files = self.m.file.listdir(
          'list files', root, recursive=True,
          test_data=['foo/ec-private/fingerprint/bar', 'bar/file'])
      source_list = [
          x for x in files
          if all(not str(x).startswith(str(p)) for p in private_dirs)
      ]
      if not source_list:
        return None

      chroot_path = lambda x: '/' + self.m.path.relpath(x, self._chroot)
      tarball = out_path.join(_FIRMWARE_TARBALL_NAME)
      cmd = ['tar', 'cvjf', chroot_path(tarball), '-C', chroot_path(root)]
      # The list of files is generally too long.
      cmd += ['--null', '-T', '/dev/stdin']
      file_list = '\0'.join(self.m.path.relpath(x, root) for x in source_list)
      self('create tarball', cmd, stdin=self.m.raw_io.input(data=file_list))
      return tarball

  def _bundle_firmware(self, chroot, sysroot, artifacts_info, outpath,
                       test_data):
    """Returns a dictionary of files by artifact_type."""
    # We always provide FIRMWARE_TARBALL and FIRMWARE_TARBALL_INFO.

    ret = {}
    # We need a directory inside of the chroot.  Use mkdtemp() to get a name, so
    # that test expectations are constant.
    tmppath = self.m.path.mkdtemp(prefix='firmware-bundle')
    tmpdir = self._chroot.join('tmp', self.m.path.basename(tmppath))
    tarball = self._build_firmware_archive(tmpdir)
    if tarball:
      self.m.file.copy('bundle tarball', tarball,
                       outpath.join(_FIRMWARE_TARBALL_NAME))
      ret['FIRMWARE_TARBALL'] = [_FIRMWARE_TARBALL_NAME]

      metadata = firmware.FirmwareArtifactInfo()
      info = metadata.objects.add()
      info.file_name = _FIRMWARE_TARBALL_NAME
      info.tarball_info.bcs_version = str(
          self.m.cros_version.read_workspace_version())
      self.m.file.write_proto('write firmware metadata',
                              outpath.join(_FIRMWARE_METADATA_NAME), metadata,
                              'JSONPB')
      ret['FIRMWARE_TARBALL_INFO'] = [_FIRMWARE_METADATA_NAME]
    return ret

  def run(self):
    with self._setup():
      self._setup_board()
      self._install_packages()
      self.m.build_menu.upload_artifacts(
          private_bundle_func=self._bundle_firmware)


def RunSteps(api, properties):
  return FirmwareBuilder(api, properties).run()


def GenTests(api):

  def test(name, *args, **kwargs):
    kwargs.setdefault('builder', 'fw-ec-postsubmit')
    kwargs.setdefault('revision', None)
    kwargs.setdefault(
        'input_properties',
        dict(firmware_location=1, manifest_branch='firmware-board-9999.B',
             packages=[dict(category='cat', package_name='chromeos-firmware')]))
    build = api.test_util.test_child_build('target', **kwargs).build
    return api.test(name, build, *args)

  legacy_setup_board = api.path.exists(api.path['start_dir'].join(
      'chromiumos_workspace', 'src', 'scripts', 'setup_board'))

  yield test('postsubmit')

  yield test(
      'no-firmware',
      api.step_data('upload artifacts.create firmware archive.list files',
                    api.file.listdir()))

  yield test('cq', cq=True, builder='fw-ec-cq')
  yield test('chroot-exists',
             api.path.exists(api.src_state.workspace_path.join('chroot')))

  yield test('old-cq', legacy_setup_board, cq=True, builder='fw-ec-cq')
