# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for modifying images for mass deployment. Intended for use with ChromeOS Flex."""

from PB.recipes.chromeos.build_mass_deploy import BuildMassDeployProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/archive',
    'recipe_engine/bcid_reporter',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_infra_config',
    'easy',
    'failures',
]


PROPERTIES = BuildMassDeployProperties

RELEASE_BUCKET = 'chromeos-releases'
THROWAWAY_BUCKET = 'chromeos-throw-away-bucket'

# When this was a manual process this was the chosen size. I don't know why.
# Doc describing the original process:
# https://docs.google.com/document/d/1npLSOGnn_2CqaTh0y_iuHJuc3xViG_GC3Z5SP5xP0os/edit?resourcekey=0-aYWwlLKts-sbcakq0Ars3g
DEFAULT_IMAGE_SIZE_GIBIBYTES = 29


def _download_signed_image(api, input_image):
  with api.step.nest('download signed image'):
    api.gsutil.download(RELEASE_BUCKET, input_image, 'image.zip')
    api.archive.extract('unzip image archive',
                        api.context.cwd.join('image.zip'),
                        api.context.cwd.join('image_dir'))

    image_name, _ = api.path.splitext(input_image)
    image_name = api.path.basename(image_name)
    decompressed_image = api.context.cwd.join('image_dir', image_name)
    return decompressed_image


def _create_empty_image(api, output_dir, image_size):
  output_image = output_dir / 'mass_deployable_image.bin'
  api.step(
      'create empty image', cmd=[
          'qemu-img',
          'create',
          '-f',
          'raw',
          '-o',
          f'size={image_size}G',
          output_image,
      ])
  return output_image


def _run_automatic_install(api, installer_image, output_image):
  """Use qemu to install, using our installer_image, into output_image"""
  with api.step.nest('set up automatic installation'):
    # Use the UEFI-triggered auto-install feature to start installation.
    # We use OVMF, an implementation of UEFI for VMs, to run in UEFI mode.
    # OVMF provides OVMF_VARS.fd files which can store UEFI variables, but
    # doesn't provide a utility for editing them. We use virt-firmware to
    # set up an OVMF_VARS file with the correct var to trigger install.
    ovmf_source_dir = '/usr/share/OVMF'
    ovmf_vars_source = 'OVMF_VARS.fd'
    # Provided by the ovmf package.
    api.file.copy('copy UEFI variables file',
                  api.path.join(ovmf_source_dir, ovmf_vars_source),
                  api.context.cwd)
    ovmf_vars_file = api.context.cwd.join(ovmf_vars_source)

    api.step(
        'create UEFI variable to trigger automatic installation', cmd=[
            'vpython3',
            '-vpython-spec',
            api.resource('.vpython3'),
            '-m',
            'virt.firmware.vars',
            '--set-json',
            api.resource('autoinstall_var.json'),
            '-i',
            ovmf_vars_file,
            '-o',
            ovmf_vars_file,
        ])

  # This will shut down when the install finishes.
  step_result = api.step(
      'boot input image to install to output image', timeout=360, cmd=[
          'qemu-system-x86_64',
          '-machine',
          'q35,smm=on',
          '-m',
          '8G',
          '-smp',
          '8',
          '-cpu',
          'qemu64',
          '-vga',
          'virtio',
          '-display',
          'none',
          '-serial',
          'none',
          '-drive',
          f'if=pflash,format=raw,readonly=on,file={ovmf_source_dir}/OVMF_CODE.fd',
          '-drive',
          f'if=pflash,format=raw,readonly=on,file={ovmf_vars_file}',
          '-hda',
          installer_image,
          '-hdb',
          output_image,
      ])

  # qemu returns 0 when killed for the timeout. Manually check if we hit the
  # timeout and raise if we did.
  if step_result.exc_result.had_timeout:  # pragma: nocover
    # There's no way to simulate "had_exception" in tests, so use nocover.
    raise StepFailure('install timed out')


def _compress_and_upload_mass_deploy_image(api, output_dir, gs_bucket, gs_dir):
  """Zip our output_dir and upload it to gs_dir in the gs_bucket"""
  zip_name = api.path.basename(output_dir) + '.zip'

  output_zip = api.archive.package(output_dir).archive(
      'compress mass deploy image', api.context.cwd.join(zip_name), 'zip')

  with api.step.nest('upload mass deploy image'):
    # Construct path for new artifact, upload to GS.
    gs_path = api.path.join(gs_dir, zip_name)
    api.gsutil.upload(output_zip, gs_bucket, gs_path)
    # Create provenance.
    # TODO(b/292108614): Remove ignore_exceptions when stable.
    with api.failures.ignore_exceptions():
      if not api.cros_infra_config.is_staging:
        file_hash = api.file.file_hash(output_zip, test_data='deadbeef')
        gs_uri = 'gs://%s/%s' % (gs_bucket, gs_path)
        api.bcid_reporter.report_gcs(file_hash, gs_uri)


def _strip_hybrid_mbr(api, output_image):
  """Remove the hybrid mbr from the mass deploy image

  We don't support mass deploy for non-UEFI devices, so the MBR support isn't
  necessary and can even cause problems (b/291059385).
  """
  # https://linux.die.net/man/8/gdisk
  gdisk_commands = (
      # Enter "eXpert mode".
      'x',
      # New protective MBR, "Use this option [...] if you want to convert a
      # hybrid MBR into a 'pure' GPT with a conventional protective MBR."
      'n',
      # Back to Main menu.
      'm',
      # Write data.
      'w',
      # Answer yes when asked if we want to write changes.
      'Y',
      # Final return.
      '')
  # Use easy.step for stdin_data
  api.easy.step('strip hybrid MBR', stdin_data='\n'.join(gdisk_commands),
                cmd=['gdisk', output_image])


def RunSteps(api, properties):
  if not properties.input_image:
    raise StepFailure('`input_image` is required')

  with api.failures.ignore_exceptions():
    if not api.cros_infra_config.is_staging:
      api.bcid_reporter.report_stage('start')
      api.bcid_reporter.report_stage('fetch')

  dest_bucket = THROWAWAY_BUCKET if api.cros_infra_config.is_staging else RELEASE_BUCKET

  image_size = properties.image_size_gib or DEFAULT_IMAGE_SIZE_GIBIBYTES

  working_dir = api.path.mkdtemp()
  with api.context(cwd=working_dir):
    installer_image = _download_signed_image(api, properties.input_image)

    output_dir = 'mass_deployable_image'
    if properties.milestone:
      output_dir += '_R' + properties.milestone
    output_dir = api.context.cwd.join(output_dir)
    api.step('create output dir', cmd=['mkdir', output_dir])

    with api.failures.ignore_exceptions():
      if not api.cros_infra_config.is_staging:
        api.bcid_reporter.report_stage('compile')

    with api.step.nest('create mass deploy image'):
      output_image = _create_empty_image(api, output_dir, image_size)
      _run_automatic_install(api, installer_image, output_image)
      _strip_hybrid_mbr(api, output_image)

    with api.failures.ignore_exceptions():
      if not api.cros_infra_config.is_staging:
        api.bcid_reporter.report_stage('upload')
    # Path in gs that our input image came from: upload back to that.
    input_path = api.path.dirname(properties.input_image)
    _compress_and_upload_mass_deploy_image(api, output_dir, dest_bucket,
                                           input_path)

    with api.failures.ignore_exceptions():
      if not api.cros_infra_config.is_staging:
        api.bcid_reporter.report_stage('upload-complete')


def GenTests(api):
  yield api.test(
      'release',
      api.properties(**{
          'input_image': 'foo/bar.zip',
          'milestone': '140',
      }),
      api.post_check(post_process.StepCommandContains,
                     'download signed image.gsutil download',
                     ['gs://chromeos-releases/foo/bar.zip']),
      api.post_check(post_process.StepSuccess, 'create mass deploy image'),
      api.post_check(post_process.StepSuccess,
                     'create mass deploy image.strip hybrid MBR'),
      api.post_check(post_process.StepSuccess, 'compress mass deploy image'),
      api.post_check(
          post_process.StepCommandContains,
          'upload mass deploy image.gsutil upload',
          ['gs://chromeos-releases/foo/mass_deployable_image_R140.zip']),
      api.post_check(post_process.MustRun,
                     'upload mass deploy image.snoop: report_gcs'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'staging',
      api.properties(**{
          'input_image': 'foo/bar.zip',
          'milestone': '140',
      }), api.buildbucket.generic_build(bucket='staging'),
      api.post_check(post_process.StepCommandContains,
                     'download signed image.gsutil download',
                     ['gs://chromeos-releases/foo/bar.zip']),
      api.post_check(post_process.StepSuccess, 'create mass deploy image'),
      api.post_check(post_process.StepSuccess,
                     'create mass deploy image.strip hybrid MBR'),
      api.post_check(post_process.StepSuccess, 'compress mass deploy image'),
      api.post_check(
          post_process.StepCommandContains,
          'upload mass deploy image.gsutil upload', [
              'gs://chromeos-throw-away-bucket/foo/mass_deployable_image_R140.zip'
          ]),
      api.post_check(post_process.DoesNotRun,
                     'upload mass deploy image.snoop: report_gcs'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-milestone', api.properties(**{
          'input_image': 'foo/bar.zip',
      }),
      api.post_check(post_process.StepCommandContains,
                     'download signed image.gsutil download',
                     ['gs://chromeos-releases/foo/bar.zip']),
      api.post_check(post_process.StepSuccess, 'create mass deploy image'),
      api.post_check(post_process.StepSuccess,
                     'create mass deploy image.strip hybrid MBR'),
      api.post_check(post_process.StepSuccess, 'compress mass deploy image'),
      api.post_check(post_process.StepCommandContains,
                     'upload mass deploy image.gsutil upload',
                     ['gs://chromeos-releases/foo/mass_deployable_image.zip']),
      api.post_check(post_process.MustRun,
                     'upload mass deploy image.snoop: report_gcs'),
      api.post_process(post_process.DropExpectation))

  yield api.test('no-input-image',
                 api.post_process(post_process.DropExpectation),
                 status='FAILURE')

  yield api.test(
      'install-timeout',
      api.properties(**{
          'input_image': 'foo/bar.zip',
          'milestone': '140',
      }),
      api.step_data(
          'create mass deploy image.boot input image to install to output image',
          times_out_after=361),
      api.post_check(
          post_process.StepFailure,
          'create mass deploy image.boot input image to install to output image'
      ), api.post_process(post_process.DropExpectation), status='FAILURE')
