# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Upload a kzip so Kythe can provide language support services for ChromeOS.

This recipe checks out a Chrom(e|ium)OS manifest, syncs it to the latest
snapshot, and builds packages with FEATURES=noclean so that build artifacts are
preserved. Then the `package_index_cros` script creates a compilation database
for all supported packages, and the `package_index` script bundles it into a
kzip file. That file gets uploaded to Kythe (go/kythe), which will index it to
serve cross-references to both Code Search and Cider G.

Note: the "ChromiumOS" in the name is outdated. Originally this recipe was
written with the assumption that it used the public ChromiumOS manifest. Now the
internal manifest can be specified via input properties.
"""

from typing import Iterable

from PB.chromite.api import sysroot as sysroot_pb2
from PB.chromiumos import common as common_pb2
from PB.recipes.chromeos import (chromiumos_codesearch as
                                 chromiumos_codesearch_pb2)
from recipe_engine import config_types
from recipe_engine import post_process
from recipe_engine import recipe_api

DEPS = [
    'infra/codesearch',
    'depot_tools/bot_update',
    'depot_tools/gclient',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'cros_build_api',
    'cros_infra_config',
    'cros_sdk',
    'cros_source',
    'easy',
]

PROPERTIES = chromiumos_codesearch_pb2.ChromiumosCodesearchProperties

def RunSteps(api, properties):

  # Shorthand common variables.
  codesearch_mirror_revision = properties.codesearch_mirror_revision
  codesearch_mirror_revision_timestamp = properties.codesearch_mirror_revision_timestamp
  build_target = api.build_menu.build_target.name
  corpus = properties.corpus
  packages = properties.packages
  sync_generated_files = properties.sync_generated_files
  experimental = properties.experimental

  # Get infra/infra.
  cache_dir = api.path.cache_dir / 'builder'
  api.gclient.set_config('infra_superproject')

  # Set up the workspace and build packages.
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():

    config.build.use_flags.append(
        common_pb2.UseFlag(flag='compilation_database'))

    env_info = api.build_menu.setup_sysroot_and_determine_relevance()
    api.build_menu.bootstrap_sysroot(config)
    api.build_menu.install_packages(config=config, packages=env_info.packages,
                                    timeout_sec=60 * 60 * 12)

    # Start the process of creating a kzip.
    build_dir = api.cros_source.workspace_path / 'src' / 'out' / build_target
    with api.context(cwd=api.cros_source.workspace_path):

      generate_compilation_database(api, build_dir, build_target, packages)

      chromeos_src_dir = api.cros_source.workspace_path / 'src'
      api.codesearch.set_config(
          'chromeos',
          PROJECT='chromeos',
          CHECKOUT_PATH=chromeos_src_dir,
          PLATFORM=build_target,
          EXPERIMENTAL=experimental,
          SYNC_GENERATED_FILES=sync_generated_files,
          CORPUS=corpus,
      )

      # Download chromium clang tools.
      clang_dir = api.codesearch.clone_clang_tools(cache_dir)

      # Run the translation_unit tool in chromeos/src dirs.
      target_architecture = _get_target_architecture(api, build_target)

      # TODO: b/327501932#comment78 - translation_unit does not work properly
      # when target_architecture is passed in.
      #
      # For amd64, if the compdb contains a clang command with the argument
      # "-march=x86-64", then running translation_unit without
      # "target_architecture" creates a valid kzip, but including
      # "target_architecture" causes compilation errors during Kythe indexing
      # and an incomplete kzip will be created.
      #
      # For arm64, if the compdb contains a clang command with the argument
      # "-march=armv8-a", then running translation_unit errors out with
      # "unknown target CPU" error and no kzip will be created.
      # While including "target_architecture" in translation_unit causes
      # compilation errors during Kythe indexing and creates an incomplete kzip,
      # having an incomplete kzip with 50% of references is considerably better than
      # not having any references at all.
      #
      # In summary, we specify "target_architecture" for "arm64" but not for "amd64"
      # to maximize kzip references across architectures.
      #
      # We want to debug the problem of why specifying "target_architecture" in
      # translation_unit leads to compilation errors for both "amd64" and "arm64" so
      # that there are any missing references.
      translation_unit_args = {
          'clang_dir': clang_dir,
          'run_dirs': [chromeos_src_dir / 'platform2']
      }
      if target_architecture != 'amd64':
        translation_unit_args['target_architecture'] = target_architecture

      api.codesearch.run_clang_tool(**translation_unit_args)

      # Create the kythe index pack and upload it to google storage.

      # package_index needs a gn_targets.json file. Since we don't use one for
      # chromeos codesearch, write an empty json file.
      # TODO(gavinmak): Make gn_targets optional in package_index.
      api.file.write_json('write empty gn_targets.json file',
                          build_dir / 'gn_targets.json', {})
      package_index_args = {
          'commit_hash':
              codesearch_mirror_revision,
          'commit_timestamp':
              int(codesearch_mirror_revision_timestamp or api.time.time()),
          'checkout_dir':
              chromeos_src_dir
      }
      if target_architecture != 'amd64':
        package_index_args['clang_target_arch'] = target_architecture

      kzip_path = api.codesearch.create_and_upload_kythe_index_pack(
          **package_index_args)


      # Check out the generated files repo and sync the generated files
      # into this checkout.
      copy_config = {
          # ~/chromeos/src/out/${build_target};src/out/${build_target}
          build_dir: api.path.join('src', 'out', build_target),

          # ~/cros_chroot/chroot;chroot
          api.build_menu.chroot.path: 'chroot',

          # ~/cros_chroot/out;out
          api.build_menu.chroot.out_path: 'out',
      }

      # Don't sync chroot/home/ nor out/home. The directory doesn't contain any
      # relevant files for cross-references.
      ignore = (
          api.path.join(api.build_menu.chroot.path, 'home'),
          api.path.join(api.build_menu.chroot.out_path, 'home'),
      )

      api.codesearch.checkout_generated_files_repo_and_sync(
          copy_config, kzip_path=kzip_path, ignore=ignore,
          revision=codesearch_mirror_revision)


def generate_compilation_database(
    api: recipe_api.RecipeApi,
    build_dir: config_types.Path,
    build_target: str,
    packages: Iterable[str],
) -> None:
  """Generate a compilation database for all the given packages.

  Args:
    api: The recipe API.
    build_dir: The directory that should contain files from the build process.
    build_target: The build target to build packages for.
    packages: A list of package names to build.
  """
  workspace = api.cros_source.workspace_path
  script_dir = workspace / 'chromite' / 'contrib' / 'package_index_cros'
  chromite_bin_path = workspace / 'chromite' / 'bin'
  with api.context(
      cwd=script_dir,
      env={'PATH': api.path.pathsep.join([str(chromite_bin_path), '%(PATH)s'])},
  ):
    api.step('run package_index_cros', [
        script_dir / 'main',
        '--debug',
        '--board',
        build_target,
        '--chroot',
        api.build_menu.chroot.path,
        '--chroot-out',
        api.build_menu.chroot.out_path,
        '--build-dir',
        build_dir,
        '--compile-commands',
        build_dir / 'compile_commands.json',
        *packages,
    ])


def _get_target_architecture(api: recipe_api.RecipeApi,
                             build_target: str) -> str:
  """Return the given build target's architecture, such as "amd64"."""
  request = sysroot_pb2.GetTargetArchitectureRequest(
      build_target=common_pb2.BuildTarget(name=build_target),
      chroot=api.cros_sdk.chroot,
  )
  response = api.cros_build_api.SysrootService.GetTargetArchitecture(request)
  return response.architecture


# TODO(crbug/1284439): Add more tests.
def GenTests(api):

  yield api.build_menu.test(
      'basic',
      api.properties(
          codesearch_mirror_revision='a' * 40,
          codesearch_mirror_revision_timestamp='1531887759',
          corpus='chrome-internal.googlesource.com/chromeos/superproject//main',
          packages=[
              'virtual/target-chromium-os', 'virtual/target-chromiumos-test'
          ],
          sync_generated_files=True,
          experimental=False,
      ),
      api.post_check(post_process.StepCommandDoesNotContain,
                     'run translation_unit clang tool',
                     ['--tool-arg=--extra-arg=--target=amd64']),
      api.post_check(post_process.StepCommandDoesNotContain,
                     'create kythe index pack',
                     ['--clang_target_arch', 'amd64']),
      api.post_process(
          post_process.PropertyEquals, 'commit', '''{
  "host": "chrome-internal.googlesource.com",
  "project": "chromeos/manifest-internal",
  "id": "d3adb33f",
  "ref": "refs/heads/snapshot"
}'''),
      builder_name='amd64-generic-codesearch',
      bucket='codesearch',
      git_ref='refs/heads/snapshot',
      git_repo='chrome-internal.googlesource.com/chromeos/manifest-internal',
      revision='d3adb33f',
  )

  yield api.build_menu.test(
      'arm64',
      api.properties(
          codesearch_mirror_revision='a' * 40,
          codesearch_mirror_revision_timestamp='1531887759',
          corpus='chrome-internal.googlesource.com/chromeos/superproject//main',
          packages=[
              'virtual/target-chromium-os', 'virtual/target-chromiumos-test'
          ],
          sync_generated_files=True,
          experimental=False,
      ),
      api.cros_build_api.set_api_return(
          '', endpoint='SysrootService/GetTargetArchitecture',
          data='{"architecture": "arm64"}'),
      api.post_check(post_process.StepCommandContains,
                     'run translation_unit clang tool',
                     ['--tool-arg=--extra-arg=--target=arm64']),
      api.post_check(post_process.StepCommandContains,
                     'create kythe index pack',
                     ['--clang_target_arch', 'arm64']),
      builder_name='arm64-generic-codesearch',
      bucket='codesearch',
      git_ref='refs/heads/snapshot',
      git_repo='chrome-internal.googlesource.com/chromeos/manifest-internal',
      revision='d3adb33f',
  )
