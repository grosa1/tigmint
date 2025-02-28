#!/usr/bin/env python3
"""
Group linked reads into molecules.
@author: Justin Chu and Shaun Jackman
"""

import os
import argparse
import statistics
import sys
import pysam
from enum import Enum

class FileFormat(Enum):
    """File format"""
    BED = 1
    TSV = 2

class Molecule:
    """A molecule of linked reads"""

    def __init__(
            self, rname, start, end, \
            new_molec_id, barcode, count, \
            mapq_median, as_median, nm_median):
        self.rname = rname
        self.start = start
        self.end = end
        self.barcode = barcode
        self.new_molec_id = new_molec_id
        self.count = count
        self.mapq_median = mapq_median
        self.as_median = as_median
        self.nm_median = nm_median

    def print_bed(self, file):
        """Print this molecule to a BED file"""
        print(
            self.rname, self.start, self.end,
            self.barcode,
            self.count,
            sep="\t", file=file)

    def print_tsv(self, file):
        """Print this molecule to a TSV file"""
        print(
            self.rname, self.start, self.end, self.end - self.start,
            self.barcode, self.new_molec_id,
            self.count,
            self.mapq_median, self.as_median, self.nm_median,
            sep="\t", file=file)

    def print_molecule(self, file, output_format):
        """Print this molecule to a file"""
        if output_format == FileFormat.BED:
            self.print_bed(file)
        if output_format == FileFormat.TSV:
            self.print_tsv(file)

class MolecIdentifier:
    """Group molecules into barcodes"""

    def __init__(self):
        """Constructor, identifies molecules based on inter-arrival time threshold."""
        self.opt = None

    def run(self):
        """Group molecules into barcodes"""

        self.parse_arguments()
        samfile = pysam.AlignmentFile(self.opt.in_bam_filename, "rb")

        if self.opt.out_bam_filename:
            out_bam_file = pysam.AlignmentFile(self.opt.out_bam_filename, "wb", template=samfile)
        else:
            out_bam_file = None

        if self.opt.out_molecules_filename:
            out_molecules_file = open(self.opt.out_molecules_filename, "w")
        else:
            out_molecules_file = sys.stdout

        if self.opt.output_format == FileFormat.TSV:
            print(
                "Rname\tStart\tEnd\tSize\tBX\tMI\tReads\tMapq_median\tAS_median\tNM_median",
                file=out_molecules_file)

        prev_barcode = None
        prev_chr = None
        cur_reads = []

        new_molec_id = 0
        for read in samfile:
            barcode = None
            if read.is_unmapped \
            or read.is_supplementary \
            or read.mapping_quality < self.opt.min_mapq \
            or read.has_tag("NM") and read.get_tag("NM") >= self.opt.max_nm:
                continue
            if read.has_tag("AS") \
                    and read.get_tag("AS") < self.opt.min_as_ratio * read.query_length:
                continue            

            if not read.has_tag("BX"):
                if out_bam_file:
                    out_bam_file.write(read)
                continue

            barcode = read.get_tag("BX")
            if prev_chr is None or prev_barcode is None:
                prev_barcode = barcode
                prev_chr = read.reference_id
            if prev_barcode != barcode or read.reference_id != prev_chr:
                prev_val = 0
                prev_read = cur_reads[0]
                prev_val1 = 0
                prev_val2 = 0
                start = cur_reads[0].pos
                rname = cur_reads[0].reference_name
                mapqs = []
                scores = []
                nms = []
                count = 0

                for cur_read in cur_reads:
                    value = cur_read.pos
                    abs_dist = value - prev_val
                    mapqs.append(cur_read.mapping_quality)
                    if cur_read.has_tag("AS"):
                        scores.append(cur_read.get_tag("AS"))
                    if cur_read.has_tag("NM"):
                        nms.append(cur_read.get_tag("NM"))

                    # Check if molecules should be terminated
                    if abs_dist > self.opt.max_dist and prev_val > 0:
                        end = prev_read.reference_end

                        # Find distance from nearest read
                        molec = Molecule(rname, start, end, \
                                 new_molec_id, prev_barcode, count, \
                                 statistics.median(mapqs), \
                                 statistics.median(scores) if scores else "NA", \
                                 statistics.median(nms) if nms else "NA")

                        if prev_read.is_reverse:
                            prev_val2 = value
                            prev_val1 = 0
                        else:
                            prev_val1 = value
                            prev_val2 = 0
                        start = value
                        if count >= self.opt.min_reads and molec.end - molec.start >= self.opt.min_size:
                            molec.print_molecule(out_molecules_file, self.opt.output_format)
                            new_molec_id += 1
                        if self.opt.out_bam_filename:
                            cur_read.set_tag("MI", new_molec_id)
                            out_bam_file.write(cur_read)
                        mapqs = []
                        scores = []
                        nms = []
                        mapqs.append(cur_read.mapping_quality)
                        if cur_read.has_tag("AS"):
                            scores.append(cur_read.get_tag("AS"))
                        if cur_read.has_tag("NM"):
                            nms.append(cur_read.get_tag("NM"))
                        prev_val = value
                        count = 0
                        continue
                    else:
                        if self.opt.out_bam_filename:
                            cur_read.set_tag("MI", new_molec_id)
                            out_bam_file.write(cur_read)

                    # Inter arrival time is distance between read of the same direction
                    inter_arrival = 0
                    if cur_read.is_reverse:
                        if prev_val2 == 0:
                            prev_val2 = value
                            prev_val = value
                            count += 1
                            continue
                        else:
                            inter_arrival = value - prev_val2
                            prev_val2 = value
                    else:
                        if prev_val1 == 0:
                            prev_val1 = value
                            prev_val = value
                            count += 1
                            continue
                        else:
                            inter_arrival = value - prev_val1
                            prev_val1 = value
                    if inter_arrival > 0:
                        count += 1
                    prev_val = value
                    prev_read = cur_read
                end = prev_read.reference_end
                molec = Molecule(rname, start, end, \
                                new_molec_id, prev_barcode, count, \
                                statistics.median(mapqs), \
                                statistics.median(scores) if scores else "NA", \
                                statistics.median(nms) if nms else "NA")

                if count >= self.opt.min_reads and molec.end - molec.start >= self.opt.min_size:
                    molec.print_molecule(out_molecules_file, self.opt.output_format)
                    new_molec_id += 1
                cur_reads = []
            cur_reads.append(read)
            prev_barcode = barcode
            prev_chr = read.reference_id

        # Clean up
        samfile.close()
        if out_molecules_file != sys.stdout:
            out_molecules_file.close()
        if out_bam_file != None:
            out_bam_file.close()
    
    def get_dist(self):
        """Read calculated dist from parameter file."""
        if os.access(self.opt.param_file, os.F_OK):
            if os.access(self.opt.param_file, os.R_OK):
                with open(self.opt.param_file) as param_file:
                    for line in param_file:
                        line_content = line.strip().split("\t")
                        if line_content[0].startswith("read_p"):
                            return int(line_content[1])
                print("tigmint-molecule: calculated max_dist parameter not found in parameter file '%'" % self.opt.param_file, file=sys.stderr)
                sys.exit(1)
            else:
                print("tigmint-molecule: parameter file '%s' cannot be read" % self.opt.param_file, file=sys.stderr)
                sys.exit(1)
        else:
            print("tigmint-molecule: parameter file '%s' cannot be read" % self.opt.param_file, file=sys.stderr)
            sys.exit(1)


    def parse_arguments(self):
        """Parse the command line arguments."""
        parser = argparse.ArgumentParser(
            description="Group linked reads into molecules. "
            "Read a SAM/BAM file and output a TSV file. "
            "The SAM/BAM file must be sorted by BX tag and then by position.")
        parser.add_argument(
            '--version', action='version', version='tigmint-molecule 1.2.9')
        parser.add_argument(
            metavar="BAM", dest="in_bam_filename",
            help="Input BAM file sorted by BX tag then position, - for stdin")
        parser.add_argument(
            "-o", "--output", dest="out_molecules_filename",
            help="Output TSV file [stdout]",
            metavar="FILE")
        parser.add_argument(
            "-w", "--out-bam", dest="out_bam_filename",
            help="Output BAM file with MI tags (optional)",
            metavar="FILE")
        parser.add_argument(
            "--bed", action="store_const", dest="output_format", const=FileFormat.BED,
            default=FileFormat.BED,
            help="Output in BED format [default]")
        parser.add_argument(
            "--tsv", action="store_const", dest="output_format", const=FileFormat.TSV,
            help="Output in TSV format")
        parser.add_argument(
            "-d", "--dist", dest="max_dist", type=int, default=50000,
            help="Maximum distance between reads in the same molecule [50000]",
            metavar="N")
        parser.add_argument(
            "-m", "--reads", dest="min_reads", type=int, default=4,
            help="Minimum number of reads per molecule (duplicates are filtered out) [4]",
            metavar="N")
        parser.add_argument(
            "-q", "--mapq", dest="min_mapq", type=int, default=0,
            help="Minimum mapping quality [0]",
            metavar="N")
        parser.add_argument(
            "-a", "--as-ratio", dest="min_as_ratio", type=float, default=0.65,
            help="Minimum ratio of alignment score (AS) over read length [0.65]",
            metavar="N")
        parser.add_argument(
            "-n", "--nm", dest="max_nm", type=int, default=5,
            help="Maximum number of mismatches (NM) [5]",
            metavar="N")
        parser.add_argument(
            "-s", "--size", dest="min_size", type=int, default=2000,
            help="Minimum molecule size [2000]",
            metavar="N")
        parser.add_argument(
            "-p", "--params", dest="param_file", type=str, default=None)
        
        self.opt = parser.parse_args()
        
        # Use calculated max dist if parameter file is provided
        if self.opt.param_file:
            self.opt.max_dist = self.get_dist()

if __name__ == '__main__':
    MolecIdentifier().run()
