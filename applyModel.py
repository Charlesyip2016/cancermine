import sys
import itertools
import kindred
import pickle
import argparse
import codecs
import time
import re
import string
from collections import defaultdict,Counter
import spacy

nlp = spacy.load('en')

def acronymMatch(words,pos,currentAcronym,atStart,subpos=None):
	if len(currentAcronym) == 0:
		if not (subpos is None): # Can't finish acronym mid-word
			return []
		else:
			return [pos+1]

	curWord = words[pos].lower()
	wordSplit = curWord.split('-')
	curLetter = currentAcronym[-1]
	
	#print curWord,curLetter
	
	moves = []
	
	if subpos is None:
		if atStart and curLetter == 's' and curWord[-1] == 's':
			# Possible plural
			moves.append( (words,pos,currentAcronym[:-1],False) )
			
		if curLetter == curWord[0]:
			moves.append( (words,pos-1,currentAcronym[:-1],False) )

	if len(wordSplit) > 1:
		if subpos is None:
			subpos = len(wordSplit)-1
		if len(wordSplit[subpos]) > 0 and curLetter == wordSplit[subpos][0]:
			if subpos == 0:
				moves.append( (words,pos-1,currentAcronym[:-1],False) )
			else:
				moves.append( (words,pos,currentAcronym[:-1],False,subpos-1) )
			
	possibleStarts = []
	for move in moves:
		possibleStarts += acronymMatch(*move)
		
	return possibleStarts

def acronymDetection(words):
	#print words
	#sys.exit(0)
	LRBs = [i for i, x in enumerate(words) if x == u'(']
	RRBs = [i for i, x in enumerate(words) if x == u')']
	acronyms = []
	for i,j in itertools.product(LRBs,RRBs):
		if j-i == 2:
			acronymLoc = i+1
			possibleAcronym = words[acronymLoc]
			possibleStarts = acronymMatch(words,i-1,possibleAcronym.lower(),True)
			#print possibleStarts
			if len(possibleStarts) > 0:
				start = min(possibleStarts)
				end = i
				acronyms.append((start,end,acronymLoc))
	return acronyms

def fusionGeneDetection(words, lookupDict):
	termtypesAndids,terms,locs = [],[],[]
	origWords = list(words)
	words = [ w.lower() for w in words ]

	for i,word in enumerate(words):
		split = re.split("[-/]",word)
		fusionCount = len(split)
		if fusionCount == 1:
			continue
			
		allGenes = True
		
		geneIDs = ['combo']
		lookupIDCounter = Counter()
		for s in split:
			key = (s,)
			if key in lookupDict:
				isGene = False
				for entityType,entityID in lookupDict[key]:
					if entityType == 'gene':
						for tmpID in entityID.split(';'):
							lookupIDCounter[tmpID] += 1

						geneIDs.append(entityID)
						isGene = True
						break
				if not isGene:
					allGenes = False
					break
			else:
				allGenes = False
				break

		# We're going to check if there are any lookup IDs shared among all the "fusion" terms
		# Hence this may not actually be a fusion, but just using multiple names of a gene
		# e.g. HER2/neu
		completeLookupIDs = [ id for id,count in lookupIDCounter.items() if count == fusionCount ]
		if len(completeLookupIDs) > 0:
			geneIDs = completeLookupIDs
	
		if allGenes:
			#geneTxt = ",".join(map(str,geneIDs))
			termtypesAndids.append([('gene','|'.join(geneIDs))])
			terms.append(tuple(origWords[i:i+1]))
			locs.append((i,i+1))
			
	return locs,terms,termtypesAndids

def getTermIDsAndLocations(np, lookupDict):
	termtypesAndids,terms,locs = [],[],[]
	# Lowercase all the tokens
	#np = [ unicodeLower(w) for w in np ]
	orignp = np
	np = [ w.lower() for w in np ]

	# The length of each search string will decrease from the full length
	# of the text down to 1
	for l in reversed(range(1, len(np)+1)):
		# We move the search window through the text
		for i in range(len(np)-l+1):
			# Extract that window of text
			s = tuple(np[i:i+l])
			# Search for it in the dictionary
			if s in lookupDict:
				# If found, save the ID(s) in the dictionary
				termtypesAndids.append(lookupDict[s])
				terms.append(tuple(orignp[i:i+l]))
				locs.append((i,i+l))
				# And blank it out
				np[i:i+l] = [ "" for _ in range(l) ]

	# Then return the found term IDs
	return locs,terms,termtypesAndids


def processWords(words, lookup, detectFusionGenes=True, detectMicroRNA=True, detectAcronyms=True, mergeTerms=True):
	locs,terms,termtypesAndids = getTermIDsAndLocations(words,lookup)

	if detectFusionGenes:
		fusionLocs,fusionTerms,fusionTermtypesAndids = fusionGeneDetection(words,lookup)
		
		termtypesAndids += fusionTermtypesAndids
		terms += fusionTerms
		locs += fusionLocs

	if detectMicroRNA:
		for i,w in enumerate(words):
			lw = w.lower()
			if lw.startswith("mir-") or lw.startswith("hsa-mir-") or lw.startswith("microrna-") or (lw.startswith("mir") and len(lw) > 3 and lw[3] in string.digits):
				termtypesAndids.append([('gene','mirna|'+w)])
				terms.append((w,))
				locs.append((i,i+1))


	filtered = zip(locs,terms,termtypesAndids)
	filtered = sorted(filtered)


	if mergeTerms:
		# We'll attempt to merge terms (i.e. if a gene is referred to using two acronyms together)
		# Example: Hepatocellular carcinoma (HCC) or HER2/ Neu or INK4B P15
		locsToRemove = set()
		for i in range(len(filtered)-1):
			(startA,endA),termsA,termTypesAndIDsA = filtered[i]
			(startB,endB),termsB,termTypesAndIDsB = filtered[i+1]
			
			# Check that the terms are beside each other or separated by a /,- or (
			if startB == endA or (startB == (endA+1) and words[endA] in ['/','-','(',')']):
				idsA,idsB = set(),set()

				for termType, termIDs in termTypesAndIDsA:
					for termID in termIDs.split(';'):
						idsA.add((termType,termID))
				for termType, termID in termTypesAndIDsB:
					for termID in termIDs.split(';'):
						idsB.add((termType,termID))

				idsIntersection = idsA.intersection(idsB)

				# Detect if the either term is in brackets e.g. HER2 (ERBB2)
				firstTermInBrackets,secondTermInBrackets = False,False
				if startB == (endA+1) and endB < len(words) and words[endA] == '(' and words[endB] == ')':
					secondTermInBrackets = True
				if startB == (endA+1) and startA > 0 and words[startA-1] == '(' and words[endA] == ')':
					firstTermInBrackets = True

				# The two terms share IDs so we're going to merge them
				idsShared = (len(idsIntersection) > 0)

				if idsShared:
					groupedByType = defaultdict(list)
					for termType,termID in idsIntersection:
						groupedByType[termType].append(termID)

					locsToRemove.add((startA,endA))
					locsToRemove.add((startB,endB))

					if secondTermInBrackets:
						thisLocs = (startA,endB+1)
						thisTerms = tuple(words[startA:endB+1])
					elif firstTermInBrackets:
						thisLocs = (startA-1,endB)
						thisTerms = tuple(words[startA-1:endB])
					else:
						thisLocs = (startA,endB)
						thisTerms = tuple(words[startA:endB])


					thisTermTypesAndIDs = [ (termType,";".join(sorted(termIDs))) for termType,termIDs in groupedByType.items() ]

					filtered.append((thisLocs,thisTerms,thisTermTypesAndIDs))

		# Now we have to remove the terms marked for deletion in the previous section
		filtered = [ (locs,terms,termtypesAndids) for locs,terms,termtypesAndids in filtered if not locs in locsToRemove]
		filtered = sorted(filtered)

	if detectAcronyms:
		# And we'll check to see if there are any obvious acronyms
		locsToRemove = set()
		acronyms = acronymDetection(words)
		for (wordsStart,wordsEnd,acronymLoc) in acronyms:
			wordIsTerm = (wordsStart,wordsEnd) in locs
			acronymIsTerm = (acronymLoc,acronymLoc+1) in locs
			
			if wordIsTerm and acronymIsTerm:
				# Remove the acronym
				locsToRemove.add((acronymLoc,acronymLoc+1))
			elif acronymIsTerm:
				# Remove any terms that contain part of the spelt out word
				newLocsToRemove = [ (i,j) for i in range(wordsStart,wordsEnd) for j in range(i,wordsEnd+1) ]
				locsToRemove.update(newLocsToRemove)
			

		# Now we have to remove the terms marked for deletion in the previous section
		filtered = [ (locs,terms,termtypesAndids) for locs,terms,termtypesAndids in filtered if not locs in locsToRemove]
		filtered = sorted(filtered)

	return filtered


def loadWordlists(entityTypesWithFilenames):
	lookup = defaultdict(set)
	for entityType,filename in entityTypesWithFilenames.items():
		with codecs.open(filename,'r','utf-8') as f:
			tempLookup = defaultdict(set)
			for line in f:
				termid,terms = line.strip().split('\t')
				for term in terms.split('|'):
					#tupleterm = tuple(term.split())
					tupleterm = tuple([ token.text.lower() for token in nlp(term) ])
					#lookup[tupleterm].add((entityType,termid))
					tempLookup[tupleterm].add(termid)

		for tupleterm,idlist in tempLookup.items():
			lookup[tupleterm].add( (entityType,";".join(sorted(list(idlist)))) )

	#lookup = { k:sorted(list(kset)) for k,kset in lookup.items() }

	return lookup

def now():
	return time.strftime("%Y-%m-%d %H:%M:%S")

def getDefiniteTerm(text,externalID,IDToTerm):
	definiteTerms = [ IDToTerm[eid] for eid in externalID.split(';') ]
	definiteTerms = sorted(list(set(definiteTerms)))
	if text.lower() in definiteTerms:
		definiteTerm = text.lower()
	else:
		definiteTerm = ";".join(definiteTerms)
	return definiteTerm

def standardizeMIRName(externalID):
	mirNumber = ""
	for c in externalID:
		if c in string.digits:
			mirNumber += c
	assert externalID.endswith(mirNumber)
	definiteTerm = "miR-%s" % mirNumber
	return definiteTerm

def cancermine(biocFile,inModel_Driver,inModel_Oncogene,inModel_TumorSuppressor,filterTerms,wordlistPickle,genes,cancerTypes,outData):
	print("%s : start" % now())

	models = {}
	with open(inModel_Driver,'rb') as f:
		models['driver'] = pickle.load(f)
	with open(inModel_Oncogene,'rb') as f:
		models['oncogene'] = pickle.load(f)
	with open(inModel_TumorSuppressor,'rb') as f:
		models['tumorsuppressor'] = pickle.load(f)

	IDToTerm = {}
	with codecs.open(genes,'r','utf-8') as f:
		for line in f:
			geneid,singleterm,_ = line.strip().split('\t')
			IDToTerm[geneid] = singleterm

	with codecs.open(cancerTypes,'r','utf-8') as f:
		for line in f:
			cancerid,singleterm,_ = line.strip().split('\t')
			IDToTerm[cancerid] = singleterm

	with codecs.open(filterTerms,'r','utf-8') as f:
		filterTerms = [ line.strip().lower() for line in f ]

	with open(wordlistPickle,'rb') as f:
		termLookup = pickle.load(f)
	#termLookup = loadWordlists({'gene':genes,'cancer':cancerTypes})
	
	# Truncate the output file
	with codecs.open(outData,'w','utf-8') as outF:
		pass

	timers = Counter()

	print("%s : processing..." % now())
	parser = kindred.Parser()
	for corpusno,corpus in enumerate(kindred.iterLoadDataFromBioc(biocFile)):
		startTime = time.time()
		parser.parse(corpus)
		timers['parser'] += time.time() - startTime
		print("%s : parsed" % now())

		startTime = time.time()
		for doc in corpus.documents:
			#print(doc.sourceIDs)
			sys.stdout.flush()
			for sentence in doc.sentences:
				words = [ t.word for t in sentence.tokens ]

				extractedTermData = processWords(words,termLookup)
				
				for locs,terms,termtypesAndids in extractedTermData:
					#text = " ".join(terms)
					startToken = locs[0]
					endToken = locs[1]
					startPos = sentence.tokens[startToken].startPos
					endPos = sentence.tokens[endToken-1].endPos
					text = doc.text[startPos:endPos]
					loc = list(range(startToken,endToken))
					for entityType,externalID in termtypesAndids:
						e = kindred.Entity(entityType,text,[(startPos,endPos)],externalID=externalID)
						doc.addEntity(e)
						sentence.addEntityWithLocation(e,loc)
		timers['entitiesAdded'] += time.time() - startTime

		print("%s : entities added" % now())

		with codecs.open(outData,'a','utf-8') as outF:
			startTime = time.time()
			for modelname,model in models.items():
				model.predict(corpus)
			timers['predicted'] += time.time() - startTime

			print("%s : predicted" % now())

			startTime = time.time()

			for doc in corpus.documents:
				if len(doc.relations) == 0:
					continue

				eID_to_sentence = {}
				for sentence in doc.sentences:
					for eID in sentence.getEntityIDs():
						eID_to_sentence[eID] = sentence
				eID_to_entity = doc.getEntityIDsToEntities()

				for relation in doc.relations:
					sentence = eID_to_sentence[relation.entityIDs[0]]
					sentenceTextLower = sentence.text.lower()

					hasFilterTerm = any( filterTerm in sentenceTextLower for filterTerm in filterTerms )
					if not hasFilterTerm:
						continue
					#words = [ t.word for t in sentence.tokens ]
					#text = " ".join(words)

					relType = relation.relationType
					entityData = []
					for eID in relation.entityIDs:
						entity = eID_to_entity[eID]
						entityData.append(entity.externalID)
						entityData.append(entity.text)


						if entity.externalID.startswith('combo'):
							_,t1,t2 = entity.externalID.split('|')
							d1 = getDefiniteTerm("",t1,IDToTerm)
							d2 = getDefiniteTerm("",t2,IDToTerm)
							definiteTerm = "%s|%s" % (d1,d2)
						elif entity.externalID.startswith('mirna|'):
							definiteTerm = standardizeMIRName(entity.externalID)
						else:
							definiteTerm = getDefiniteTerm(entity.text,entity.externalID,IDToTerm)

						entityData.append(definiteTerm)


					if doc.metadata["pmid"]:
						m = doc.metadata
						outData = [m["pmid"],m['title'],m["journal"],m["year"],m['section'],relType] + entityData + [sentence.text]
						outLine = "\t".join(outData)
						outF.write(outLine+"\n")

			timers['output'] += time.time() - startTime

			print("%s : output" % now())

		#if corpusno > 5:
		#	break
		#break
		sys.stdout.flush()

	print("%s : done" % now())
	
	for section,sectiontime in timers.items():
		print("%s\t%f" % (section,sectiontime))


if __name__ == '__main__':
	parser = argparse.ArgumentParser(description='Finds relations in Pubmed file')
	parser.add_argument('--biocFile',required=True,help='BioC XML file to use')
	parser.add_argument('--inModel_Driver',required=True)
	parser.add_argument('--inModel_Oncogene',required=True)
	parser.add_argument('--inModel_TumorSuppressor',required=True)
	parser.add_argument('--filterTerms',required=True)
	parser.add_argument('--wordlistPickle',required=True)
	parser.add_argument('--genes',required=True)
	parser.add_argument('--cancerTypes',required=True)
	parser.add_argument('--outData',required=True)

	args = parser.parse_args()

	cancermine(args.biocFile,args.inModel_Driver,args.inModel_Oncogene,args.inModel_TumorSuppressor,args.filterTerms,args.wordlistPickle,args.genes,args.cancerTypes,args.outData)
