import kindred
import argparse
import pickle
import os

if __name__ == '__main__':
	parser = argparse.ArgumentParser(description='Build and save a classifier')
	parser.add_argument('--inTrain',type=str,required=True)
	parser.add_argument('--outModel',type=str,required=True)

	args = parser.parse_args()

	print("Loading training")
	goldDir = 'gold'
	trainCorpus = kindred.loadDir(dataFormat='standoff',directory=args.inTrain)

	print("Doing training")
	features = "entityTypes,unigramsBetweenEntities,bigrams,dependencyPathEdges,dependencyPathEdgesNearEntities".split(',')
	classifier = kindred.RelationClassifier(classifierType='LogisticRegression',threshold=0.8,features=features,acceptedEntityPairs=[('cancer','gene')])
	classifier.train(trainCorpus)

	print("Saving classifer")
	with open(args.outModel,'wb') as f:
		pickle.dump(classifier,f)

	print("Done!")
