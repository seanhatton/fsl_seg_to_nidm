#!/usr/bin/env python
#!/usr/bin/env python
#**************************************************************************************
#**************************************************************************************
#  fsl_seg_to_nidm.py
#  License: GPL
#**************************************************************************************
#**************************************************************************************
# Date: June 6, 2019                 Coded by: Brainhack'ers
# Filename: fsl_seg_to_nidm.py
#
# Program description:  This program will load in JSON output from FSL's FAST/FIRST
# segmentation tool, augment the FSL anatomical region designations with common data element
# anatomical designations, and save the statistics + region designations out as
# NIDM serializations (i.e. TURTLE, JSON-LD RDF)
#
#
#**************************************************************************************
# Development environment: Python - PyCharm IDE
#
#**************************************************************************************
# System requirements:  Python 3.X
# Libraries: PyNIDM,
#**************************************************************************************
# Start date: June 6, 2019
# Update history:
# DATE            MODIFICATION				Who
#
#
#**************************************************************************************
# Programmer comments:
#
#
#**************************************************************************************
#**************************************************************************************


from nidm.core import Constants
from nidm.experiment.Core import getUUID
from nidm.experiment.Core import Core
from prov.model import QualifiedName,PROV_ROLE, ProvDocument, PROV_ATTR_USED_ENTITY,PROV_ACTIVITY,PROV_AGENT,PROV_ROLE

from prov.model import Namespace as provNamespace

# standard library
from pickle import dumps
import os
from os.path import join,basename,splitext,isfile,dirname
from socket import getfqdn
import glob

import prov.model as prov
import json
import urllib.request as ur
from urllib.parse import urlparse
import re

from rdflib import Graph, RDF, URIRef, util, term,Namespace,Literal,BNode,XSD
from fsl_seg_to_nidm.fslutils import read_fsl_stats, convert_stats_to_nidm, create_cde_graph
from io import StringIO

import tempfile


def url_validator(url):
    '''
    Tests whether url is a valide url
    :param url: url to test
    :return: True for valid url else False
    '''
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc, result.path])

    except:
        return False

def add_seg_data(nidmdoc,subjid,fs_stats_entity_id, add_to_nidm=False, forceagent=False):
    '''
    WIP: this function creates a NIDM file of brain volume data and if user supplied a NIDM-E file it will add brain volumes to the
    NIDM-E file for the matching subject ID
    :param nidmdoc:
    :param header:
    :param add_to_nidm:
    :return:
    '''


    #for each of the header items create a dictionary where namespaces are freesurfer
    niiri=Namespace("http://iri.nidash.org/")
    nidmdoc.bind("niiri",niiri)
    # add namespace for subject id
    ndar = Namespace(Constants.NDAR)
    nidmdoc.bind("ndar",ndar)
    dct = Namespace(Constants.DCT)
    nidmdoc.bind("dct",dct)
    sio = Namespace(Constants.SIO)
    nidmdoc.bind("sio",sio)


    software_activity = niiri[getUUID()]
    nidmdoc.add((software_activity,RDF.type,Constants.PROV['Activity']))
    nidmdoc.add((software_activity,Constants.DCT["description"],Literal("FSL FAST/FIRST segmentation statistics")))
    fs = Namespace(Constants.FSL)


    #create software agent and associate with software activity
    #search and see if a software agent exists for this software, if so use it, if not create it
    for software_uid in nidmdoc.subjects(predicate=Constants.NIDM_NEUROIMAGING_ANALYSIS_SOFTWARE,object=URIRef(Constants.FSL) ):
        software_agent = software_uid
        break
    else:
        software_agent = niiri[getUUID()]

    nidmdoc.add((software_agent,RDF.type,Constants.PROV['Agent']))
    neuro_soft=Namespace(Constants.NIDM_NEUROIMAGING_ANALYSIS_SOFTWARE)
    nidmdoc.add((software_agent,Constants.NIDM_NEUROIMAGING_ANALYSIS_SOFTWARE,URIRef(Constants.FSL)))
    nidmdoc.add((software_agent,RDF.type,Constants.PROV["SoftwareAgent"]))
    association_bnode = BNode()
    nidmdoc.add((software_activity,Constants.PROV['qualifiedAssociation'],association_bnode))
    nidmdoc.add((association_bnode,RDF.type,Constants.PROV['Association']))
    nidmdoc.add((association_bnode,Constants.PROV['hadRole'],Constants.NIDM_NEUROIMAGING_ANALYSIS_SOFTWARE))
    nidmdoc.add((association_bnode,Constants.PROV['agent'],software_agent))

    # Initialize participant_agent to None to prevent UnboundLocalError
    participant_agent = None

    if not add_to_nidm:

        # create a new agent for subjid
        participant_agent = niiri[getUUID()]
        nidmdoc.add((participant_agent,RDF.type,Constants.PROV['Agent']))
        nidmdoc.add((participant_agent,URIRef(Constants.NIDM_SUBJECTID.uri),Literal(subjid, datatype=XSD.string)))

    else:
        # query to get agent id for subjid
        #find subject ids and sessions in NIDM document
            query = """
                    PREFIX ndar:<https://ndar.nih.gov/api/datadictionary/v2/dataelement/>
                    PREFIX rdf:<http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                    PREFIX prov:<http://www.w3.org/ns/prov#>
                    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

                    select distinct ?agent
                    where {

                        ?agent rdf:type prov:Agent ;
                        ndar:src_subject_id \"%s\"^^xsd:string .

                    }""" % subjid
            #print(query)
            qres = nidmdoc.query(query)
            if len(qres) == 0:
                print('Subject ID (%s) was not found in existing NIDM file...' %subjid)
                ##############################################################################
                # added to account for issues with some BIDS datasets that have leading 00's in subject directories
                # but not in participants.tsv files.
                qres2 = []
                if (len(subjid) - len(subjid.lstrip('0'))) != 0:
                    print('Trying to find subject ID without leading zeros....')
                    query = """
                        PREFIX ndar:<https://ndar.nih.gov/api/datadictionary/v2/dataelement/>
                        PREFIX rdf:<http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                        PREFIX prov:<http://www.w3.org/ns/prov#>
                        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

                        select distinct ?agent
                        where {

                            ?agent rdf:type prov:Agent ;
                            ndar:src_subject_id \"%s\"^^xsd:string .

                        }""" % subjid.lstrip('0')
                    #print(query)
                    qres2 = nidmdoc.query(query)
                    if len(qres2) == 0:
                        print("Still can't find subject id after stripping leading zeros...")
                    else:
                        for row in qres2:
                            print('Found subject ID after stripping zeros: %s in NIDM file (agent: %s)' %(subjid.lstrip('0'),row[0]))
                            participant_agent = row[0]
                #######################################################################################
                if (forceagent is not False) and (len(qres2) == 0):
                    print('Explicitly creating agent in existing NIDM file...')
                    participant_agent = niiri[getUUID()]
                    nidmdoc.add((participant_agent,RDF.type,Constants.PROV['Agent']))
                    nidmdoc.add((participant_agent,URIRef(Constants.NIDM_SUBJECTID.uri),Literal(subjid, datatype=XSD.string)))
                elif (forceagent is False) and (len(qres) == 0) and (len(qres2) == 0):
                    print('Not explicitly adding agent to NIDM file, no output written')
                    exit()
            else:
                 for row in qres:
                    print('Found subject ID: %s in NIDM file (agent: %s)' %(subjid,row[0]))
                    participant_agent = row[0]

    #create a blank node and qualified association with prov:Agent for participant
    association_bnode = BNode()
    nidmdoc.add((software_activity,Constants.PROV['qualifiedAssociation'],association_bnode))
    nidmdoc.add((association_bnode,RDF.type,Constants.PROV['Association']))
    nidmdoc.add((association_bnode,Constants.PROV['hadRole'],Constants.SIO["Subject"]))
    nidmdoc.add((association_bnode,Constants.PROV['agent'],participant_agent))

    # add association between FSStatsCollection and computation activity
    nidmdoc.add((URIRef(fs_stats_entity_id.uri),Constants.PROV['wasGeneratedBy'],software_activity))

    # get project uuid from NIDM doc and make association with software_activity
    query = """
                        prefix nidm: <http://purl.org/nidash/nidm#>
                        PREFIX rdf:<http://www.w3.org/1999/02/22-rdf-syntax-ns#>

                        select distinct ?project
                        where {

                            ?project rdf:type nidm:Project .

                        }"""

    qres = nidmdoc.query(query)
    for row in qres:
        nidmdoc.add((software_activity, Constants.DCT["isPartOf"], row['project']))

def test_connection(remote=False):
    """helper function to test whether an internet connection exists.
    Used for preventing timeout errors when scraping interlex."""
    import socket
    remote_server = 'www.google.com'
    try:
        # Resolve hostname using getaddrinfo (supports both IPv4 and IPv6)
        addr_info = socket.getaddrinfo(remote_server, 80, socket.AF_UNSPEC)
        host = addr_info[0][4][0]
        # can we establish a connection to the host?
        con = socket.create_connection((host, 80), 2)
        return True
    except:
        print("Can't connect to a server...")
        return False



def main():

    import argparse
    parser = argparse.ArgumentParser(prog='fsl_seg_to_nidm.py',
                                     description='''This program will load in JSON output from FSL's FAST/FIRST
                                        segmentation tool, augment the FSL anatomical region designations with common data element
                                        anatomical designations, and save the statistics + region designations out as
                                        NIDM serializations (i.e. TURTLE, JSON-LD RDF)''',
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    #DBK: added mutually exclusive arguments to support pulling a named stats file (e.g. aseg.stats) as a URL such as
    #data hosted in an amazon bucket or from a mounted filesystem where you don't have access to the original
    #subjects directory.

    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument('-d', '--data_file', dest='data_file', type=str,
                        help='Path to FSL FIRST/FAST JSON data file')
    group.add_argument('-f', '--seg_file', dest='segfile', type=str,help='Path or URL to a specific FSL JSON'
                            'stats file. Note, currently this is tested on ReproNim data')
    parser.add_argument('-subjid','--subjid',dest='subjid',required=True, help='If a path to a URL or a stats file'
                            'is supplied via the -f/--seg_file parameters then -subjid parameter must be set with'
                            'the subject identifier to be used in the NIDM files')
    parser.add_argument('-o', '--output', dest='output_dir', type=str,
                        help='Output filename with full path', required=True)
    parser.add_argument('-j', '--jsonld', dest='jsonld', action='store_true', default = False,
                        help='If flag set then NIDM file will be written as JSONLD instead of TURTLE')
    parser.add_argument('-add_de', '--add_de', dest='add_de', action='store_true', default = None,
                        help='If flag set then data element data dictionary will be added to nidm file else it will written to a'
                            'separate file as fsl_cde.ttl in the output directory (or same directory as nidm file if -n paramemter'
                            'is used.')
    parser.add_argument('-n','--nidm', dest='nidm_file', type=str, required=False,
                        help='Optional NIDM file to add segmentation data to.')
    parser.add_argument('-forcenidm','--forcenidm', action='store_true',required=False,
                        help='If adding to NIDM file this parameter forces the data to be added even if the participant'
                             'doesnt currently exist in the NIDM file.')

    args = parser.parse_args()

    # test whether user supplied stats file directly and if so they the subject id must also be supplied so we
    # know which subject the stats file is for
    if (args.segfile and (args.subjid is None)) or (args.data_file and (args.subjid is None)):
        parser.error("-f/--seg_file and -d/--data_file requires -subjid/--subjid to be set!")

    # if output_dir doesn't exist then create it
    out_path = os.path.dirname(args.output_dir)
    if not os.path.exists(out_path):
        os.makedirs(out_path)


    # if we set -s or --subject_dir as parameter on command line...
    if args.data_file is not None:


        measures =read_fsl_stats(args.data_file)
        [e, doc] = convert_stats_to_nidm(measures)
        g = create_cde_graph()

        # for measures we need to create NIDM structures using anatomy mappings
        # If user has added an existing NIDM file as a command line parameter then add to existing file for subjects who exist in the NIDM file
        if args.nidm_file is None:

            print("Creating NIDM file...")
            # If user did not choose to add this data to an existing NIDM file then create a new one for the CSV data

            # convert nidm stats graph to rdflib
            g2 = Graph()
            g2.parse(source=StringIO(doc.serialize(format='rdf',rdf_format='turtle')),format='turtle')

            if args.add_de is not None:
                nidmdoc = g+g2
            else:
                nidmdoc = g2

            # print(nidmdoc.serializeTurtle())

            # add seg data to new NIDM file
            add_seg_data(nidmdoc=nidmdoc,subjid=args.subjid,fs_stats_entity_id=e.identifier)

             #serialize NIDM file
            print("Writing NIDM file...")
            if args.jsonld is not False:
                #nidmdoc.serialize(destination=join(args.output_dir,splitext(basename(args.data_file))[0]+'.json'),format='jsonld')
                nidmdoc.serialize(destination=join(args.output_dir),format='jsonld')
            else:
                # nidmdoc.serialize(destination=join(args.output_dir,splitext(basename(args.data_file))[0]+'.ttl'),format='turtle')
                nidmdoc.serialize(destination=join(args.output_dir),format='turtle')
            # added to support separate cde serialization
            if args.add_de is None:
                # serialize cde graph
                g.serialize(destination=join(dirname(args.output_dir),"fsl_cde.ttl"),format='turtle')

        # we adding these data to an existing NIDM file
        else:
           #read in NIDM file with rdflib
            g1 = Graph()
            g1.parse(args.nidm_file,format=util.guess_format(args.nidm_file))

            # convert nidm stats graph to rdflib
            g2 = Graph()
            g2.parse(source=StringIO(doc.serialize(format='rdf',rdf_format='turtle')),format='turtle')

            if args.add_de is not None:
                print("Combining graphs...")
                nidmdoc = g + g1 + g2
            else:
                nidmdoc = g1 + g2

            if args.forcenidm is not False:
                add_seg_data(nidmdoc=nidmdoc,subjid=args.subjid,fs_stats_entity_id=e.identifier,add_to_nidm=True, forceagent=True)
            else:
                add_seg_data(nidmdoc=nidmdoc,subjid=args.subjid,fs_stats_entity_id=e.identifier,add_to_nidm=True)


            #serialize NIDM file
            print("Writing Augmented NIDM file...")
            if args.jsonld is not False:
                nidmdoc.serialize(destination=args.nidm_file + '.json',format='jsonld')
            else:
                nidmdoc.serialize(destination=args.nidm_file,format='turtle')

            if args.add_de is None:
                # serialize cde graph
                g.serialize(destination=join(dirname(args.output_dir),"fsl_cde.ttl"),format='turtle')

    # else if the user didn't set subject_dir on command line then they must have set a segmentation file directly
    elif args.segfile is not None:

        #WIP: FSL URL form: https://fcp-indi.s3.amazonaws.com/data/Projects/ABIDE/Outputs/mindboggle_swf/simple_workflow/sub-0050002/segstats.json

        # here we're supporting amazon bucket-style file URLs where the expectation is the last parameter of the
        # see if we have a valid url
        url = url_validator(args.segfile)
        # if user supplied a url as a segfile
        if url is not False:

            #try to open the url and get the pointed to file
            try:
                #open url and get file
                opener = ur.urlopen(args.segfile)
                # write temporary file to disk and use for stats
                temp = tempfile.NamedTemporaryFile(delete=False)
                temp.write(opener.read())
                temp.close()
                stats_file = temp.name
            except:
                print("ERROR! Can't open url: %s" %args.segfile)
                exit()

            # since all of the above worked, all we need to do is set the output file name to be the
            # args.subjid + "_" + [everything after the last / in the supplied URL]
            url_parts = urlparse(args.segfile)
            path_parts = url_parts[2].rpartition('/')
            output_filename = args.subjid + "_" + splitext(path_parts[2])[0]

        # else this must be a path to a stats file
        else:
            if isfile(args.segfile):
                stats_file = args.segfile
                # set outputfilename to be the args.subjid + "_" + args.segfile
                output_filename = args.subjid + "_" + splitext(basename(args.segfile))[0]
            else:
                print("ERROR! Can't open stats file: %s " %args.segfile)
                exit()

        measures =read_fsl_stats(stats_file)
        [e, doc] = convert_stats_to_nidm(measures)
        g = create_cde_graph()


        # for measures we need to create NIDM structures using anatomy mappings
        # If user has added an existing NIDM file as a command line parameter then add to existing file for subjects who exist in the NIDM file
        if args.nidm_file is None:

            print("Creating NIDM file...")
            # If user did not choose to add this data to an existing NIDM file then create a new one for the CSV data

            # convert nidm stats graph to rdflib
            g2 = Graph()
            g2.parse(source=StringIO(doc.serialize(format='rdf',rdf_format='turtle')),format='turtle')

            if args.add_de is not None:
                nidmdoc = g+g2
            else:
                nidmdoc = g2

            # print(nidmdoc.serializeTurtle())

            # add seg data to new NIDM file
            add_seg_data(nidmdoc=nidmdoc,subjid=args.subjid,fs_stats_entity_id=e.identifier)

             #serialize NIDM file
            print("Writing NIDM file...")
            if args.jsonld is not False:
                # nidmdoc.serialize(destination=join(args.output_dir,splitext(basename(args.data_file))[0]+'.json'),format='jsonld')
                nidmdoc.serialize(destination=join(args.output_dir),format='jsonld')
            else:
                # nidmdoc.serialize(destination=join(args.output_dir,splitext(basename(args.data_file))[0]+'.ttl'),format='turtle')
                nidmdoc.serialize(destination=join(args.output_dir),format='turtle')

            # added to support separate cde serialization
            if args.add_de is None:
                # serialize cde graph
                g.serialize(destination=join(dirname(args.output_dir),"fsl_cde.ttl"),format='turtle')


        # we adding these data to an existing NIDM file
        else:
           #read in NIDM file with rdflib
            g1 = Graph()
            g1.parse(args.nidm_file,format=util.guess_format(args.nidm_file))

            # convert nidm stats graph to rdflib
            g2 = Graph()
            g2.parse(source=StringIO(doc.serialize(format='rdf',rdf_format='turtle')),format='turtle')

            if args.add_de is not None:
                print("Combining graphs...")
                nidmdoc = g + g1 + g2
            else:
                nidmdoc = g1 + g2

            if args.forcenidm is not False:
                add_seg_data(nidmdoc=nidmdoc,subjid=args.subjid,fs_stats_entity_id=e.identifier,add_to_nidm=True, forceagent=True)
            else:
                add_seg_data(nidmdoc=nidmdoc,subjid=args.subjid,fs_stats_entity_id=e.identifier,add_to_nidm=True)


            #serialize NIDM file
            print("Writing Augmented NIDM file...")
            if args.jsonld is not False:
                nidmdoc.serialize(destination=args.nidm_file + '.json',format='jsonld')
            else:
                nidmdoc.serialize(destination=args.nidm_file,format='turtle')

            if args.add_de is None:
                # serialize cde graph
                g.serialize(destination=join(dirname(args.output_dir),"fsl_cde.ttl"),format='turtle')

if __name__ == "__main__":
    main()
