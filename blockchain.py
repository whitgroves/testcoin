import json
import hashlib
import logging
import requests
from time import time
from uuid import uuid4
from textwrap import dedent
from urllib.parse import urlparse
from flask import Flask, jsonify, request

class Blockchain(object):
	def __init__(self):
		self.chain = []
		self.current_transactions = []
		self.nodes = set()
		#create the genesis block
		self.new_block(previous_hash=1, proof=100)
		
	def register_node(self, address):
		"""
		add a new node to the list of nodes
		:param address: <str> address of node e.g. 'http://192.168.0.5:5000'
		:return: None
		"""
		parsed_url = urlparse(address)
		self.nodes.add(parsed_url.netloc)
		
	def new_block(self, proof, previous_hash=None):
		"""
		create a new block in the blockchain
		:param proof: <int> the proof given by the proof of work algorithm
		:param previous_hash: (optional) <str> hash of previous block
		:return: <dict> new block
		"""
		block = {
			'index': len(self.chain) + 1,
			'timestamp': time(),
			'transactions': self.current_transactions,
			'proof': proof,
			'previous_hash': previous_hash or self.hash(self.chain[-1]),
		}
		#reset the current list of transactions
		self.current_transactions = []
		self.chain.append(block)
		return block
		
	def new_transaction(self, sender, recipient, amount):
		"""
		creates a new transaction to go into the next mined block
		:param sender: <str> address of the sender
		:param recipient: <str> address of the recipient
		:param amount: <int> amount
		:return: <int> the index of the block that will hold this transation
		"""
		self.current_transactions.append({
			'sender': sender,
			'recipient': recipient,
			'amount': amount
		})
		#returns the /next/ block because you can only add transactions to
		#the block currently being mined
		return self.last_block['index'] + 1
		
	@staticmethod
	def hash(block):
		"""
		creates a sha-256 hash of a block
		:param block: <dict> block
		:return: <str>
		"""
		#we must make sure that the dictionary is ordered, or we'll
		#have inconsistent hashes
		block_string = json.dumps(block, sort_keys=True).encode()
		return hashlib.sha256(block_string).hexdigest()
	
	@property
	def last_block(self):
		return self.chain[-1]
		
	def proof_of_work(self, last_proof):
		"""
		:simple proof of work algorithm:
		  - find a number p' such that hash(pp') contains leading 4 zeroes, 
		  	where p is the previous p'
		  - p is the previous proof, and p' is the new proof
		
		:param last_proof: <int>
		:return: <int>
		"""
		proof = 0
		while self.valid_proof(last_proof, proof) is False:
			proof += 1
		return proof
	
	@staticmethod
	def valid_proof(last_proof, proof):
		"""
		validates the proof: does hash(last_proof, proof) contain 4 leading 
		zeroes?
		:param last_proof: <int> previous proof
		:param proof: <int> current proof
		:return: <bool> true if correct, false if not
		"""
		guess = f'{last_proof}{proof}'
		guess_hash = hashlib.sha256(guess).hexdigest()
		return guess_hash[:4] == "0000"
		
	def valid_chain(self, chain):
		"""
		determine if a given blockchain is valid
		:param chain: <list> a blockchain
		:return: <bool> true if valid, false if not
		"""
		last_block = chain[0]
		current_index = 1
		while current_index < len(chain):
			block = chain[current_index]
			print(f'{last_block}')
			print(f'{block}')
			print("\n-----------\n")
			#check that the hash of the block is correct
			if block['previous_hash'] != self.hash(last_block):
				return False
			#check that the proof of work is correct
			if not self.valid_proof(last_block['proof'], block['proof']):
				return False
			last_block = block
			current_index += 1
		return True
	
	def resolve_conflicts(self):
		"""
		this is our consensus algorithm 
		it resolves conflicts by replacing our 
		chain with the longest one in the network
		:return: <bool> true if our chain was replaced, false if not
		"""
		neighbours = self.nodes
		new_chain = None
		#we're only looking for chains longer than ours
		max_length = len(self.chain)
		#grab and verify the chains from all the nodes in our network
		for node in neighbours:
			response = requests.get(f'http://{node}/chain')
			if response.status_code == 200:
				length = response.json()['length']
				chain = response.json()['chain']
				#check if the length is longer and the chain is valid
				if length > max_length and self.valid_chain(chain):
					max_length = length
					new_chain = chain
		if new_chain:
			self.chain = new_chain
			return True
		return False
		
#instantiate our node
app = Flask(__name__)
#create and configure logger
logging.basicConfig(filename="testcoin.log", 
					level=logging.DEBUG,
					format="%(levelname)s %(asctime)s - %(message)s",
					filemode='w')
logger = logging.getLogger()
#generate a globally unique address for this node
node_identifier = str(uuid4()).replace('-', '')
#instantiate the blockchain
blockchain = Blockchain()
logger.info("testcoin up")

@app.route('/mine', methods=['GET'])
def mine():
	#we run the proof of work algorithm to get the next proof
	last_block = blockchain.last_block
	last_proof = last_block['proof']
	proof = blockchain.proof_of_work(last_proof)
	#we must receive a reward for finding the proof
	#the sender is "0" to signify that this node has mined a new coin.
	blockchain.new_transaction(
		sender="0",
		recipient=node_identifier,
		amount=1
	)
	#forge the new block by adding it to the chain
	block = blockchain.new_block(proof)
	response = {
		'message': 'new block forged',
		'index': block['index'],
		'transactions': block['transactions'],
		'proof': block['proof'],
		'previous_hash': block['previous_hash']
	}
	return jsonify(response), 200

@app.route('/transactions/new', methods=['POST'])
def new_transaction():
	values = request.get_json()
	#check that the required fields are in the posted data
	required = ['sender', 'recipient', 'amount']
	if values is None or not all(k in values for k in required):
		return 'missing values', 400
	#create a new transaction
	index = blockchain.new_transaction(values['sender'],
									   values['recipient'],
									   values['amount'])
	response = {'message': f'transaction will be added to block {index}'}
	return jsonify(response), 201
		
@app.route('/chain', methods=['GET'])
def full_chain():
	response = {
		'chain': blockchain.chain,
		'length': len(blockchain.chain),
	}
	return jsonify(response), 200
	
@app.route('/nodes/register', methods=['POST'])
def register_nodes():
	values = request.get_json()
	nodes = values.get('nodes')
	if nodes is None:
		return "error: please supply a valid list of nodes", 400
	for node in nodes:
		blockchain.register_node(node)
	response = {
		'message': 'new nodes have been added',
		'total_nodes': list(blockchain.nodes)
	}
	return jsonify(response), 201
	
@app.route('/nodes/resolve', methods=['GET'])
def consensus():
	replaced = blockchain.resolve_conflicts()
	if replaced:
		response = {
			'message': 'our chain was replaced',
			'new_chain': blockchain.chain
		}
	else:
		response = {
			'message': 'our chain is authoratative',
			'chain': blockchain.chain
		}
	return jsonify(response), 200
	
if __name__ == '__main__':
	try:
		port = int(input('port: '))
	except ValueError:
		port = 5000
		message = f'defaulting to port {port}'
		print(message)
		logger.info(message)
	app.run(host='127.0.0.1', port=port)
		
		
		

