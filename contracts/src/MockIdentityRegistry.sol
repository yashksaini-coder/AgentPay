// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title MockIdentityRegistry — ERC-8004 Identity Registry for local testing
/// @notice Minimal ERC-721-like registry where agents mint identity tokens
contract MockIdentityRegistry {
    uint256 private _nextId = 1;

    struct Agent {
        address owner;
        string uri;
    }

    mapping(uint256 => Agent) public agents;
    mapping(address => uint256) public agentIdOf;

    event AgentRegistered(uint256 indexed agentId, address indexed owner, string uri);

    function registerAgent(string calldata uri) external returns (uint256 agentId) {
        require(agentIdOf[msg.sender] == 0, "Already registered");
        agentId = _nextId++;
        agents[agentId] = Agent({owner: msg.sender, uri: uri});
        agentIdOf[msg.sender] = agentId;
        emit AgentRegistered(agentId, msg.sender, uri);
    }

    function agentURI(uint256 agentId) external view returns (string memory) {
        require(agents[agentId].owner != address(0), "Agent not found");
        return agents[agentId].uri;
    }

    function ownerOf(uint256 agentId) external view returns (address) {
        require(agents[agentId].owner != address(0), "Agent not found");
        return agents[agentId].owner;
    }
}
