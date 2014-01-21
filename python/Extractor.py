#!/usr/bin/env python3

__version__ = "0.3.1"

import Objects
import os
import sys
import logging
import hashlib
import copy
import traceback
import dfxml

_logger = logging.getLogger(os.path.basename(__file__))

XMLNS_EXTRACTOR = "#Extractor.py"

def is_alloc_and_uncompressed(obj):
    if obj.compressed:
        return False
    if not obj.alloc_inode is None and not obj.alloc_name is None:
        return obj.alloc_inode and obj.alloc_name
    return obj.alloc

def is_file(obj):
    if is_alloc_and_uncompressed(obj) != True:
        return False
    if obj.filename is None:
        return None
    return obj.name_type == "r"
    
def is_jpeg(obj):
    if is_alloc_and_uncompressed(obj) != True:
        return False
    if obj.filename is None:
        return None
    if is_file(obj) != True:
        return False
    return obj.filename.lower().endswith(("jpg","jpeg"))

def name_with_part_path(fobj):
    retval = fobj.filename
    if fobj.partition is None:
        retval = os.path.join("no_partition", retval)
    else:
        retval = os.path.join("partition_" + str(fobj.partition), retval)
    return retval

def extract_files(image_path, outdir, dfxml_path=None, file_predicate=is_file, file_name=name_with_part_path, dry_run=None, out_manifest_path=None, err_manifest_path=None):
    """
    @param file_name Unary function.  Takes a Objects.FileObject; returns the file path to which this file will be extracted, relative to outdir.  So, if outdir="extraction" and the name_with_part_path function of this module is used, the file "/Users/Administrator/ntuser.dat" in partition 1 will be extracted to "extraction/partition_1/Users/Administrator/ntuser.dat".
    """

    extraction_byte_tally = 0

    _path_for_iterparse = dfxml_path or image_path

    #Set up base manifest to track extracted files
    base_manifest = Objects.DFXMLObject()
    base_manifest.command_line = " ".join(sys.argv)
    base_manifest.version = "1.1.0+"
    base_manifest.add_namespace("extractor", XMLNS_EXTRACTOR)
    base_manifest.add_namespace("delta", dfxml.XMLNS_DELTA)
    base_manifest.sources.append(image_path)
    if dfxml_path:
        base_manifest.sources.append(dfxml_path)

    #Clone base manifest to all-files' manifest and errors-only manifest
    out_manifest = None
    if out_manifest_path:
        out_manifest = copy.deepcopy(base_manifest)
    err_manifest = None
    if err_manifest_path:
        err_manifest = copy.deepcopy(base_manifest)

    for (event, obj) in Objects.iterparse(_path_for_iterparse):
        #Absolute prerequisites:
        if not isinstance(obj, Objects.FileObject):
            continue

        #Invoker prerequisites
        if not file_predicate(obj):
            continue

        extraction_entry = Objects.FileObject()
        extraction_entry.original_fileobject = obj

        #Construct path where the file will be extracted
        extraction_write_path = os.path.join(outdir, file_name(obj))

        #Extract idempotently
        if os.path.exists(extraction_write_path):
            _logger.debug("Skipping already-extracted file: %r.  Extraction path already exists: %r." % (obj.filename, extraction_write_path))
            continue

        extraction_entry.filename = extraction_write_path

        #Set up checksum verifier
        checker = None
        checked_byte_tally = 0
        if obj.sha1:
            checker = hashlib.sha1()

        extraction_byte_tally += obj.filesize

        any_error = None
        if not dry_run:
            extraction_write_dir = os.path.dirname(extraction_write_path)
            if not os.path.exists(extraction_write_dir):
                os.makedirs(extraction_write_dir)
            _logger.debug("Extracting to: %r." % extraction_write_path)
            with open(extraction_write_path, "wb") as extraction_write_fh:
                try:
                    for chunk in obj.extract_facet("content", image_path):
                        if checker:
                            checker.update(chunk)
                        checked_byte_tally += len(chunk)
                        extraction_write_fh.write(chunk)

                    if checked_byte_tally != obj.filesize:
                        any_error = True
                        extraction_entry.filesize = checked_byte_tally
                        extraction_entry.diffs.append("filesize")
                        _logger.error("File size mismatch on %r." % obj.filename)
                        _logger.info("Recorded filesize = %r" % obj.filesize)
                        _logger.info("Extracted bytes   = %r" % checked_byte_tally)
                    if checker and (obj.sha1 != checker.hexdigest()):
                        any_error = True
                        extraction_entry.sha1 = checker.hexdigest()
                        extraction_entry.diffs.append("sha1")
                        _logger.error("Hash mismatch on %r." % obj.filename)
                        _logger.info("Recorded SHA-1 = %r" % obj.sha1)
                        _logger.info("Computed SHA-1 = %r" % checker.hexdigest())
                        _logger.debug("File object: %r." % obj)
                except:
                    any_error = True
                    extraction_entry.error = traceback.format_stack()
        if err_manifest and any_error:
            err_manifest.append(extraction_entry)
        if out_manifest:
            out_manifest.append(extraction_entry)

    #Report
    _logger.info("Estimated extraction: %d bytes." % extraction_byte_tally)
    if not out_manifest is None:
        with open(out_manifest_path, "w") as out_manifest_fh:
            out_manifest.print_dfxml(out_manifest_fh)
    if not err_manifest is None:
        with open(err_manifest_path, "w") as err_manifest_fh:
            err_manifest.print_dfxml(err_manifest_fh)
        
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files to disk.  Only verifies computed vs. stored checksums of file content.")
    parser.add_argument("-x", "--xml", help="Pre-computed DFXML file.  If not supplied, Fiwalk is called on the image argument.")
    parser.add_argument("--output-manifest", help="Path for recording DFXML manifest of all extracted files.")
    parser.add_argument("--error-manifest", help="Path for recording DFXML manifest of only files extracted with errors.")
    parser.add_argument("image", help="Subject disk image from which files will be extracted.")
    parser.add_argument("output_directory", help="Target output directory.  Can already exist.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    extract_files(args.image, args.output_directory, args.xml, is_file, name_with_part_path, args.dry_run, args.output_manifest, args.error_manifest)
