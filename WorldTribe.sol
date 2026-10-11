// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * @title World Tribe Equilibrium Engine
 * @notice Replaces debt with universal provision.
 */
contract WorldTribe {
    address public owner;

    struct Member {
        bool isSovereign;    
        uint256 creditBalance; 
        bool inCrisis;       
    }

    mapping(address => Member) public tribe;
    uint256 public BASELINE = 1000;

    event MemberJoined(address indexed member, uint256 initialBalance);
    event BaselineUpdated(uint256 oldBaseline, uint256 newBaseline);
    event CrisisSignaled(address indexed member);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Caller is not the owner");
        _;
    }

    function transferOwnership(address _newOwner) public onlyOwner {
        require(_newOwner != address(0), "New owner is the zero address");
        emit OwnershipTransferred(owner, _newOwner);
        owner = _newOwner;
    }

    // The Global Hi
    function joinTribe() public {
        require(!tribe[msg.sender].isSovereign, "Already recognized.");
        tribe[msg.sender] = Member(true, BASELINE, false);
        emit MemberJoined(msg.sender, BASELINE);
    }

    // Simulate resource usage
    function spendCredits(uint256 _amount) public {
        require(tribe[msg.sender].isSovereign, "Not a member.");
        require(tribe[msg.sender].creditBalance >= _amount, "Insufficient credits.");
        tribe[msg.sender].creditBalance -= _amount;
    }

    // Provisioning (The Hearth)
    function maintainEquilibrium(address _member) public {
        require(tribe[_member].isSovereign, "Not a member");
        if (tribe[_member].creditBalance < BASELINE) {
            tribe[_member].creditBalance = BASELINE;
        }
    }

    // Mentorship Trigger (No More Cages)
    function triggerRedAlert() public {
        require(tribe[msg.sender].isSovereign, "Not a member");
        tribe[msg.sender].inCrisis = true;
        emit CrisisSignaled(msg.sender);
    }

    // Admin logic
    function setBaseline(uint256 _newBaseline) public onlyOwner {
        require(_newBaseline > 0, "Baseline must be positive");
        uint256 oldBaseline = BASELINE;
        BASELINE = _newBaseline;
        emit BaselineUpdated(oldBaseline, _newBaseline);
    }
}
