// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title MockReputationRegistry — ERC-8004 Reputation Registry for local testing
/// @notice Minimal feedback submission and aggregation contract
contract MockReputationRegistry {
    struct Feedback {
        address reviewer;
        uint8 score;
        string tag;
        uint256 timestamp;
    }

    mapping(uint256 => Feedback[]) public feedbackHistory;

    event FeedbackSubmitted(uint256 indexed agentId, address indexed reviewer, uint8 score, string tag);

    function submitFeedback(uint256 agentId, uint8 score, string calldata tag) external {
        require(score <= 100, "Score must be 0-100");
        feedbackHistory[agentId].push(
            Feedback({reviewer: msg.sender, score: score, tag: tag, timestamp: block.timestamp})
        );
        emit FeedbackSubmitted(agentId, msg.sender, score, tag);
    }

    function getReputationSummary(uint256 agentId) external view returns (uint8 avgScore, uint256 feedbackCount) {
        Feedback[] storage history = feedbackHistory[agentId];
        feedbackCount = history.length;
        if (feedbackCount == 0) {
            return (0, 0);
        }
        uint256 total = 0;
        for (uint256 i = 0; i < feedbackCount; i++) {
            total += history[i].score;
        }
        avgScore = uint8(total / feedbackCount);
    }
}
